"""EUREKAI background workers for video processing."""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List

import config
import database as db
from engines import activity_engine, knowledgebase, pose_engine, score_engine, video_engine

logger = logging.getLogger("ergovision.workers")
_executor: ThreadPoolExecutor = None


def init_workers(max_workers: int = 2) -> None:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=max_workers)
        logger.info("ThreadPoolExecutor with %s workers", max_workers)


def shutdown_workers() -> None:
    global _executor
    if _executor:
        _executor.shutdown(wait=True)
        _executor = None


def submit_analysis(analysis_id: int, video_path: str, lens_id: str) -> None:
    init_workers()
    logger.info("[Analysis %s] Submitted %s", analysis_id, video_path)
    _executor.submit(_run_pipeline, analysis_id, video_path, lens_id)


def _run_pipeline(analysis_id: int, video_path: str, lens_id: str) -> None:
    t0 = time.time()
    logger.info("[Analysis %s] Pipeline starting", analysis_id)

    # Reset pose detector for fresh analysis (prevents stale state between runs)
    pose_engine.reset_detector()

    try:
        db.update_analysis(analysis_id, status="processing")

        # 1. Extract frames
        frames, fps, duration = video_engine.extract_frames(video_path, target_fps=5.0)
        h, w = frames[0].shape[:2] if frames else (0, 0)
        logger.info("[Analysis %s] %s frames, %sfps, %.1fs", analysis_id, len(frames), fps, duration)

        # 2. Pose detection
        db.update_analysis(analysis_id, status="processing_pose")
        pose_frames = pose_engine.process_frames(frames, fps)
        pose_count = sum(1 for pf in pose_frames if pf.has_pose)
        logger.info("[Analysis %s] %s/%s frames with pose", analysis_id, pose_count, len(pose_frames))

        # 2a. YOLO Object Detection
        db.update_analysis(analysis_id, status="processing_objects")
        try:
            from engines import yolo_engine, interaction_engine
            objects_per_frame = yolo_engine.process_frames(frames, pose_frames)
            object_summary = yolo_engine.summarize_objects(objects_per_frame, pose_frames)
            interacting_object = object_summary.get("interacting_object")
            if interacting_object:
                logger.info("[Analysis %s] Objects detected: %s (interacting: %s)",
                            analysis_id,
                            object_summary.get("primary_object", "none"),
                            interacting_object.get("display", "unknown"))
            else:
                logger.info("[Analysis %s] Objects detected: %s", analysis_id,
                            object_summary.get("primary_object", "none"))
        except Exception as e:
            logger.warning("[Analysis %s] YOLO skipped: %s", analysis_id, e)
            objects_per_frame = [[] for _ in frames]
            object_summary = {"total_detections": 0, "unique_objects": 0, "primary_object": None, "object_list": []}

        # 2b. Interaction Detection (push/pull/carry/lift)
        interactions = interaction_engine.detect_interactions(pose_frames, objects_per_frame)
        interaction_summary = interaction_engine.summarize_interactions(interactions, object_summary)
        logger.info("[Analysis %s] Primary interaction: %s", analysis_id,
                    interaction_summary.primary_action)

        # 3. Scoring
        db.update_analysis(analysis_id, status="processing_scores")
        scores = score_engine.score_batch(pose_frames)
        rula_scores, reba_scores, safety_scores = scores["rula"], scores["reba"], scores["safety"]
        overall_safety = scores["overall_safety"]
        logger.info("[Analysis %s] Safety=%.1f", analysis_id, overall_safety)

        # 4. Evidence snapshots — multi-tier RULA/REBA based (max 12)
        db.update_analysis(analysis_id, status="processing_evidence")
        evidence = video_engine.capture_evidence(
            frames, pose_frames, rula_scores, reba_scores, safety_scores,
            config.EVIDENCE_DIR, analysis_id, max_shots=12,
            objects_per_frame=objects_per_frame,
            interacting_object=interacting_object,
        )

        # 5. Side-by-side detected vs corrected evidence
        from engines.score_engine import select_evidence_frames as sef
        selected = sef(rula_scores, reba_scores, safety_scores, pose_frames, 12)
        sbs_evidence = video_engine.generate_evidence_side_by_side(
            frames, pose_frames, safety_scores,
            config.EVIDENCE_DIR, analysis_id, selected
        )
        for ev in evidence:
            db_ev = {k: v for k, v in ev.items()
                     if k in ("image_path", "frame_number", "timestamp",
                              "rula_score", "reba_score", "safety_score",
                              "label", "risk_level")}
            db.insert_evidence(analysis_id, **db_ev)
        logger.info("[Analysis %s] %s evidence snapshots", analysis_id, len(evidence))

        # Extract explanation data for template (stored in metadata)
        evidence_explains = {}
        for ev in evidence:
            fn = ev.get("frame_number", 0)
            evidence_explains[str(fn)] = {
                "rula_explain": ev.get("rula_explain", {}),
                "reba_explain": ev.get("reba_explain", {}),
                "issues": ev.get("issues", []),
            }

        # 6. Skeleton overlay video (detected skeleton colored by safety)
        db.update_analysis(analysis_id, status="processing_videos")
        analysis_video = video_engine.generate_skeleton_video(
            frames, pose_frames, safety_scores,
            os.path.join(config.OUTPUT_DIR, f"analysis_{analysis_id}_video.mp4"), fps
        )

        # 7. Corrected skeleton video (green ideal posture + red arrows)
        corrected_video = video_engine.generate_corrected_video(
            frames, pose_frames, safety_scores,
            os.path.join(config.OUTPUT_DIR, f"corrected_{analysis_id}.mp4"), fps
        )

        # 8. Activity recognition + story generation
        db.update_analysis(analysis_id, status="processing_activity")
        activity = activity_engine.recognize_activity(pose_frames)
        story = activity_engine.generate_story(activity, pose_frames, scores)
        logger.info("[Analysis %s] Activity: %s (%s%%)", analysis_id,
                     activity["activity"], activity["confidence"])

        # 9. Pose JSON for client-side rendering (saved AFTER activity so activity is included)
        pose_json = video_engine.save_pose_data(
            pose_frames, safety_scores, rula_scores, reba_scores,
            analysis_id, fps, w, h, config.OUTPUT_DIR, activity=activity
        )
        logger.info("[Analysis %s] Pose JSON saved: %s", analysis_id, pose_json)

        # 10. Context-aware recommendations from knowledgebase
        recommendations = knowledgebase.generate_context_aware_recommendations(
            activity, pose_frames, rula_scores, reba_scores, safety_scores
        )
        logger.info("[Analysis %s] Generated %s context-aware recommendations",
                     analysis_id, len(recommendations))

        # 11. Aggregate stats
        rula_vals = [s for s in rula_scores if s is not None]
        reba_vals = [s for s in reba_scores if s is not None]
        rula_max = max(rula_vals) if rula_vals else None
        rula_mean = sum(rula_vals) / len(rula_vals) if rula_vals else None
        reba_max = max(reba_vals) if reba_vals else None
        reba_mean = sum(reba_vals) / len(reba_vals) if reba_vals else None

        elapsed = time.time() - t0

        db.update_analysis(
            analysis_id,
            status="completed",
            metadata={
                "safety_score": overall_safety,
                "rula_score": rula_mean,
                "rula_max": rula_max,
                "rula_mean": rula_mean,
                "reba_score": reba_mean,
                "reba_max": reba_max,
                "reba_mean": reba_mean,
                "video_duration": duration,
                "video_fps": fps,
                "processing_time_seconds": elapsed,
                "evidence_count": len(evidence),
                "sbs_count": len(sbs_evidence),
                "pose_frames": pose_count,
                "frame_count": len(frames),
                "analysis_video": analysis_video,
                "corrected_video": corrected_video,
                "pose_json": pose_json,
                "recommendations": recommendations,
                "activity": activity,
                "story": story,
                "object_summary": object_summary,
                "interacting_object": interacting_object,
                "interaction_summary": {
                    "primary_action": interaction_summary.primary_action,
                    "action_breakdown": interaction_summary.action_breakdown,
                    "object_interactions": interaction_summary.object_interactions,
                    "story": interaction_summary.story,
                },
                "sbs_evidence": sbs_evidence,
                "evidence_explains": evidence_explains,
                "completed_at": datetime.utcnow().isoformat(),
            },
        )
        logger.info("[Analysis %s] Completed in %.1fs", analysis_id, elapsed)

    except Exception as exc:
        logger.exception("[Analysis %s] Failed: %s", analysis_id, exc)
        db.mark_failed(analysis_id, f"{type(exc).__name__}: {exc}")


def get_progress(analysis_id: int) -> Dict[str, Any]:
    row = db.get_analysis(analysis_id)
    if not row:
        return {"status": "not_found"}
    return {
        "status": row.get("status", "unknown"),
        "analysis_id": analysis_id,
        "safety_score": row.get("safety_score"),
        "rula_score": row.get("rula_score"),
        "reba_score": row.get("reba_score"),
    }
