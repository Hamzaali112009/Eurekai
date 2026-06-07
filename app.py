"""EUREKAI Flask application."""
import json
import logging
import os
import re
import secrets
import sys
from datetime import datetime
from typing import Any, Dict, Optional

from flask import (
    Flask, Response, flash, jsonify, redirect, render_template, request,
    send_file, session, url_for,
)
from werkzeug.utils import secure_filename

# Allow imports from same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import database as db
from engines import lens_engine
from workers import get_progress, shutdown_workers, submit_analysis

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("ergovision.app")

# ── Flask App ────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static", static_url_path="/static")
app.secret_key = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH

# ── Init ─────────────────────────────────────────────────────────────
# Database auto-initializes on import


# ── Template Filters ─────────────────────────────────────────────────
@app.template_filter("risk_color")
def risk_color_filter(score: Any) -> str:
    try:
        s = float(score)
        return "var(--success)" if s >= 75 else "var(--warning)" if s >= 50 else "var(--danger)"
    except (TypeError, ValueError):
        return "var(--text-tertiary)"


@app.template_filter("risk_bg")
def risk_bg_filter(score: Any) -> str:
    try:
        s = float(score)
        if s >= 75:
            return "var(--success-bg)"
        if s >= 50:
            return "var(--warning-bg)"
        return "var(--danger-bg)"
    except (TypeError, ValueError):
        return "var(--bg-tertiary)"


@app.template_filter("risk_label")
def risk_label_filter(score: Any) -> str:
    try:
        s = float(score)
        if s >= 75:
            return "Safe"
        if s >= 50:
            return "Caution"
        return "Danger"
    except (TypeError, ValueError):
        return "N/A"


# ── Routes ───────────────────────────────────────────────────────────

@app.route("/")
def homepage():
    lens = request.args.get("lens")
    if lens and lens_engine.validate_lens(lens):
        session["lens_id"] = lens
        return redirect(url_for("upload_page", lens=lens))
    active = session.get("lens_id")
    if active and lens_engine.validate_lens(active):
        return redirect(url_for("upload_page", lens=active))
    return render_template("lens_select.html", lenses=lens_engine.list_lenses())


@app.route("/upload")
def upload_page():
    lens_id = request.args.get("lens", session.get("lens_id", "ergonomics"))
    if not lens_engine.validate_lens(lens_id):
        lens_id = "ergonomics"
    session["lens_id"] = lens_id
    lens = lens_engine.get_lens(lens_id)
    return render_template(lens["upload_template"], lens=lens, lens_id=lens_id)


@app.route("/api/upload", methods=["POST"])
def api_upload():
    lens_id = request.args.get("lens", session.get("lens_id", "ergonomics"))
    logger.info("Upload request: lens=%s, files=%s, content_length=%s",
                lens_id, list(request.files.keys()), request.content_length)
    
    if not lens_engine.validate_lens(lens_id):
        return jsonify({"error": "Invalid lens"}), 400

    if "video" not in request.files:
        logger.warning("Upload failed: no 'video' field. Available: %s", list(request.files.keys()))
        return jsonify({"error": "No video file received. Make sure you selected a video file."}), 400

    file = request.files["video"]
    if file.filename == "":
        logger.warning("Upload failed: empty filename")
        return jsonify({"error": "Empty filename"}), 400

    ext = file.filename.rsplit(".", 1)[1].lower() if "." in file.filename else ""
    # Also check MIME type for mobile files without proper extension
    mime_ext = (file.content_type or "").rsplit("/", 1)[-1].lower() if "/" in (file.content_type or "") else ""
    logger.info("Upload file: name=%s ext=%s mime=%s size=%s", file.filename, ext, file.content_type, request.content_length)
    
    if ext not in config.ALLOWED_EXTENSIONS and mime_ext not in config.ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Invalid file type: {ext or mime_ext}. Allowed: {', '.join(sorted(config.ALLOWED_EXTENSIONS))}"}), 400

    # Save upload
    fname = f"{int(datetime.utcnow().timestamp())}_{secure_filename(file.filename)}"
    fpath = os.path.join(config.UPLOAD_DIR, fname)
    file.save(fpath)

    # Create analysis record
    file_size = os.path.getsize(fpath)
    analysis_id = db.insert_analysis(
        lens=lens_id,
        filename=file.filename,
        filepath=fpath,
        file_size=file_size,
    )

    # Submit to background worker
    submit_analysis(analysis_id, fpath, lens_id)

    return jsonify({
        "success": True,
        "analysis_id": analysis_id,
        "status": "processing",
    }), 201


@app.route("/api/progress/<int:aid>")
def api_progress(aid):
    return jsonify(get_progress(aid))


@app.route("/analysis/<analysis_ref>")
def analysis_page(analysis_ref):
    """Show analysis results."""
    aid = _resolve_ref(analysis_ref)
    if aid is None:
        return render_template("errors/404.html", message="Invalid analysis reference"), 404

    analysis = db.get_analysis(aid)
    if not analysis:
        return render_template("errors/404.html", message="Analysis not found"), 404

    lens_id = analysis.get("lens_id", "ergonomics")
    lens = lens_engine.get_lens(lens_id)

    # Build full context
    ctx = _build_context(analysis)

    return render_template(lens["analysis_template"], analysis=analysis, lens=lens,
                           lens_id=lens_id, **ctx)


@app.route("/history")
def history_page():
    analyses = db.list_analyses()
    return render_template("history.html", analyses=analyses)


@app.route("/webcam")
def webcam_page():
    return render_template("webcam.html")


@app.route("/3d-viewer")
def viewer_3d():
    return render_template("3d_viewer.html")


@app.route("/video-file/<subdir>/<filename>")
def serve_file(subdir, filename):
    dirs = {"uploads": config.UPLOAD_DIR, "outputs": config.OUTPUT_DIR, "evidence": config.EVIDENCE_DIR}
    base = dirs.get(subdir)
    if not base:
        return jsonify({"error": "Invalid"}), 403
    fpath = os.path.join(base, filename)
    real_base = os.path.realpath(base)
    real_req = os.path.realpath(fpath)
    if not real_req.startswith(real_base):
        return jsonify({"error": "Invalid path"}), 403
    if not os.path.isfile(fpath):
        return jsonify({"error": "Not found"}), 404
    return send_file(fpath)


@app.route("/api/webcam/analyze", methods=["POST"])
def api_webcam_analyze():
    """Receive a webcam frame, detect pose, return landmarks + scores."""
    import tempfile

    if "frame" not in request.files:
        return jsonify({"error": "No frame provided"}), 400

    file = request.files["frame"]

    # Save to temp file
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    try:
        import cv2
        import numpy as np
        from engines import pose_engine, score_engine

        # Load image
        img = cv2.imread(tmp_path)
        if img is None:
            return jsonify({"error": "Invalid image"}), 400

        # Detect pose
        detector = pose_engine._init_detector()
        if pose_engine._api_type == "new":
            landmarks = pose_engine._detect_new(img)
        else:
            landmarks = pose_engine._detect_classic(img)

        if not landmarks or len(landmarks) < 6:
            return jsonify({"landmarks": {}, "angles": {}, "rula": 0, "reba": 0, "safety": 50, "has_pose": False})

        # Calculate angles
        angles = pose_engine._calc_angles(landmarks)

        # Score
        rula = score_engine.rula_from_angles(angles)
        reba = score_engine.reba_from_angles(angles)
        safety = score_engine.safety_from_scores(rula["total"], reba["total"])

        # Normalize landmarks (0-1)
        h, w = img.shape[:2]
        norm_lm = {}
        for idx, (x, y, vis) in landmarks.items():
            norm_lm[str(idx)] = {"x": round(x / w, 4), "y": round(y / h, 4), "v": round(vis, 3)}

        return jsonify({
            "landmarks": norm_lm,
            "angles": angles,
            "rula": rula["total"],
            "reba": reba["total"],
            "safety": safety,
            "has_pose": True,
        })

    except Exception as exc:
        logger.exception("Webcam analyze failed: %s", exc)
        return jsonify({"error": str(exc)}), 500
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


@app.route("/api/analysis/<int:aid>/pose")
def api_pose_data(aid):
    """Serve pose landmark JSON for client-side skeleton rendering."""
    pose_path = os.path.join(config.OUTPUT_DIR, f"pose_{aid}.json")
    if os.path.isfile(pose_path):
        with open(pose_path, "r") as f:
            return Response(f.read(), mimetype="application/json")
    return jsonify({"error": "Pose data not available"}), 404


@app.route("/api/analysis/<int:aid>/delete", methods=["POST"])
def api_delete(aid):
    row = db.get_analysis(aid)
    if row:
        vp = row.get("video_path", "")
        if vp and os.path.exists(vp):
            try:
                os.remove(vp)
            except Exception:
                pass
        db.update_analysis(aid, status="deleted")
    return jsonify({"success": True})


# ── Context Builder ──────────────────────────────────────────────────

def _build_context(analysis: Dict[str, Any]) -> Dict[str, Any]:
    ctx = {}
    aid = analysis.get("id", 0)

    # Parse metadata (scores and computed values are stored here)
    meta = analysis.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}

    # Basic scores — read from metadata first, fall back to direct columns
    ctx["analysis_id"] = aid
    ctx["safety_score"] = _fmt_int(meta.get("safety_score", analysis.get("safety_score", 0)))
    ctx["rula_score"] = _fmt_int(meta.get("rula_score", analysis.get("rula_score", 0)))
    ctx["reba_score"] = _fmt_int(meta.get("reba_score", analysis.get("reba_score", 0)))
    ctx["rula_max"] = _fmt_int(meta.get("rula_max", analysis.get("rula_max", 0)))
    ctx["rula_mean"] = _fmt_int(meta.get("rula_mean", analysis.get("rula_mean", 0)))
    ctx["reba_max"] = _fmt_int(meta.get("reba_max", analysis.get("reba_max", 0)))
    ctx["reba_mean"] = _fmt_int(meta.get("reba_mean", analysis.get("reba_mean", 0)))

    # Dates — read from metadata first
    created = analysis.get("created_at")
    ctx["upload_date"] = _fmt_date(created) if created else "N/A"
    dur = meta.get("video_duration", analysis.get("video_duration"))
    ctx["duration"] = _fmt_dur(dur) if dur else "N/A"
    ctx["processing_time"] = round(meta.get("processing_time_seconds", analysis.get("processing_time_seconds", 0)), 1)

    # Video URLs
    vp = analysis.get("video_path", "")
    if vp and os.path.exists(vp):
        ctx["original_video_url"] = f"/video-file/uploads/{os.path.basename(vp)}"
    else:
        ctx["original_video_url"] = ""

    # Video URLs from metadata
    av_path = meta.get("analysis_video", "") if isinstance(meta, dict) else ""
    if av_path:
        ctx["analysis_video_url"] = f"/video-file/outputs/{os.path.basename(av_path)}"
    else:
        av = os.path.join(config.OUTPUT_DIR, f"analysis_{aid}_video.mp4")
        ctx["analysis_video_url"] = f"/video-file/outputs/{os.path.basename(av)}" if os.path.exists(av) else ""

    cv_path = meta.get("corrected_video", "") if isinstance(meta, dict) else ""
    if cv_path:
        ctx["corrected_video_url"] = f"/video-file/outputs/{os.path.basename(cv_path)}"
    else:
        cv = os.path.join(config.OUTPUT_DIR, f"corrected_{aid}.mp4")
        ctx["corrected_video_url"] = f"/video-file/outputs/{os.path.basename(cv)}" if os.path.exists(cv) else ""

    # Pose data URL for canvas rendering
    ctx["pose_data_url"] = f"/api/analysis/{aid}/pose"

    # RULA breakdown — use scores already read from metadata
    r = ctx["rula_score"] or 0
    ctx["rula_arm"] = max(1, min(6, int(r * 0.6)))
    ctx["rula_neck"] = max(1, min(3, int(r * 0.3)))
    ctx["rula_trunk"] = max(1, min(3, int(r * 0.4)))
    ctx["upper_arm"] = max(1, min(6, int(r * 0.5)))
    ctx["lower_arm"] = 1
    ctx["wrist"] = max(1, min(4, int(r * 0.35)))
    ctx["wrist_twist"] = 1

    # REBA breakdown
    rb = ctx["reba_score"] or 0
    ctx["reba_posture"] = max(1, min(8, int(rb * 0.6)))
    ctx["reba_load"] = max(0, min(3, int(rb * 0.15)))
    ctx["reba_coupling"] = max(0, min(3, int(rb * 0.1)))
    ctx["neck_score"] = max(1, min(3, int(rb * 0.25)))
    ctx["trunk_score"] = max(1, min(5, int(rb * 0.35)))
    ctx["leg_score"] = 1
    ctx["activity_score"] = max(0, min(3, int(rb * 0.1)))

    # Evidence items with explanation data
    evidence_explains = meta.get("evidence_explains", {}) if isinstance(meta, dict) else {}
    ctx["evidence_items"] = _scan_evidence(aid, evidence_explains)

    # Side-by-side detected + corrected evidence
    sbs_list = meta.get("sbs_evidence", []) if isinstance(meta, dict) else []
    ctx["sbs_evidence"] = []
    for sbs in sbs_list:
        if isinstance(sbs, dict) and sbs.get("image_path"):
            fname = os.path.basename(sbs["image_path"])
            ctx["sbs_evidence"].append({
                "image_url": f"/video-file/evidence/{fname}",
                "frame_number": sbs.get("frame_number", 0),
                "tier": sbs.get("tier", "medium"),
                "rula": sbs.get("rula", 0),
                "reba": sbs.get("reba", 0),
                "safety": sbs.get("safety", 50),
            })

    # Body regions
    ctx["body_regions"] = _derive_regions(r, rb)

    # Activity recognition + story + recommendations
    # (meta already parsed above)
    activity = meta.get("activity", {}) if isinstance(meta, dict) else {}
    ctx["activity"] = activity
    ctx["activity_name"] = activity.get("activity", "unknown") if isinstance(activity, dict) else "unknown"
    ctx["activity_confidence"] = activity.get("confidence", 0) if isinstance(activity, dict) else 0
    ctx["activity_details"] = activity.get("details", "") if isinstance(activity, dict) else ""
    ctx["activity_scores"] = activity.get("scores", {}) if isinstance(activity, dict) else {}

    story = meta.get("story", "") if isinstance(meta, dict) else ""
    ctx["story"] = story

    # Detected objects + interactions
    meta = analysis.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}

    object_summary = meta.get("object_summary", {}) if isinstance(meta, dict) else {}
    ctx["object_list"] = object_summary.get("object_list", [])
    ctx["object_count"] = object_summary.get("unique_objects", 0)
    ctx["interacting_object"] = meta.get("interacting_object") if isinstance(meta, dict) else None

    interaction_data = meta.get("interaction_summary", {}) if isinstance(meta, dict) else {}
    ctx["interaction_story"] = interaction_data.get("story", "")
    ctx["primary_action"] = interaction_data.get("primary_action", "")
    ctx["action_breakdown"] = interaction_data.get("action_breakdown", {})
    ctx["object_interactions"] = interaction_data.get("object_interactions", [])

    # Recommendations (from knowledgebase, activity-specific)
    ctx["recommendations"] = _get_recs(analysis)

    return ctx


def _scan_evidence(aid: int, explains: dict = None):
    if not aid:
        return []
    rows = db.get_evidence_for_analysis(aid)
    items = []
    for row in rows:
        fname = os.path.basename(row.get("image_path", ""))
        fn = row.get("frame_number", 0)
        item = {
            "label": row.get("label", "Evidence"),
            "time": f"00:{int(row.get('timestamp', 0)) // 60:02d}:{int(row.get('timestamp', 0)) % 60:02d}",
            "risk": row.get("risk_level", "medium"),
            "image_url": f"/video-file/evidence/{fname}",
            "frame_number": fn,
            "rula_score": row.get("rula_score", 0),
            "reba_score": row.get("reba_score", 0),
            "safety_score": row.get("safety_score", 50),
        }
        # Merge explanation data if available
        if explains and str(fn) in explains:
            exp = explains[str(fn)]
            item["rula_explain"] = exp.get("rula_explain", {})
            item["reba_explain"] = exp.get("reba_explain", {})
            item["issues"] = exp.get("issues", [])
        items.append(item)
    return items


def _derive_regions(rula_total, reba_total):
    import random
    rng = random.Random(int((rula_total or 0) * 100 + (reba_total or 0) * 100))
    regions = [
        ("Neck", 0.35), ("Shoulders", 0.30), ("Upper Back", 0.25),
        ("Lower Back", 0.35), ("Hips", 0.15), ("Wrists", 0.40),
        ("Knees", 0.10), ("Ankles", 0.05),
    ]
    base = max(rula_total or 0, reba_total or 0) / 7.0 * 100
    result = []
    for name, w in regions:
        s = min(100, max(5, int(base * w + rng.randint(-10, 10))))
        c = "var(--danger)" if s >= 75 else "var(--warning)" if s >= 50 else "var(--success)"
        result.append({"name": name, "score": s, "color": c})
    return result


def _get_recs(analysis):
    """Get angle-based recommendations from DB metadata. Falls back to score-based."""
    meta = analysis.get("metadata") or {}
    if isinstance(meta, str):
        import json
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    # Real recommendations from pose analysis
    real_recs = meta.get("recommendations", []) if isinstance(meta, dict) else []
    if real_recs:
        return real_recs

    # Fallback: score-based generic
    rula = analysis.get("rula_score") or 0
    reba = analysis.get("reba_score") or 0
    recs = []
    if rula >= 5 or reba >= 8:
        recs.append({"p": "high", "title": "Fix Forward Head Posture",
                     "desc": "Tuck chin in, align ear with shoulder. Raise monitor to eye level.",
                     "meta": f"RULA {rula:.0f} elevated → Target ≤3"})
        recs.append({"p": "high", "title": "Straighten Trunk",
                     "desc": "Sit against chair backrest. Set backrest to 100-110 degrees. Increase lumbar support.",
                     "meta": f"Trunk angle elevated → Target <15°"})
    if rula >= 4 or reba >= 5:
        recs.append({"p": "medium", "title": "Relax Shoulders",
                     "desc": "Lower armrests. Keep keyboard at elbow height. Avoid reaching.",
                     "meta": f"REBA {reba:.0f} → Target ≤3"})
    if not recs:
        recs.append({"p": "low", "title": "Maintain Good Posture",
                     "desc": "Current posture is acceptable. Schedule periodic reviews.",
                     "meta": "All scores in safe range"})
    return recs


def _resolve_ref(ref: str) -> Optional[int]:
    try:
        return int(ref)
    except ValueError:
        m = re.search(r'(\d+)$', ref)
        return int(m.group(1)) if m else None


def _fmt_int(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return 0


def _fmt_date(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%b %d, %Y · %H:%M")
    except Exception:
        return str(s)


def _fmt_dur(seconds):
    try:
        s = int(float(seconds))
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"
    except (TypeError, ValueError):
        return "N/A"


# ── Error Handlers ───────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html"), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("errors/500.html"), 500


@app.teardown_appcontext
def cleanup(exception=None):
    pass


# ── Main ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import atexit
    atexit.register(shutdown_workers)
    app.run(host="0.0.0.0", port=5000, debug=False)
