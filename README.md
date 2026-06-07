# EUREKAI v5.0 — AI-Powered Ergonomic Risk Assessment

Complete standalone release with YOLO object detection and push/pull/carry/lift interaction analysis.

## What's New in v5.0

- **YOLO Object Detection** — Identifies boxes, carts, pallets, shelves, forklifts, and more
- **Push / Pull / Carry / Lift Detection** — From pose trajectory analysis
- **Object-Aware Interactions** — "Pushing cart", "Pulling handle", "Carrying box"
- **Official RULA/REBA Scoring** — McAtamney & Corlett 1993, Hignett & McAtamney 2000
- **Activity Recognition** — Desk work, standing, lifting, reaching, walking
- **3D Pose Viewer** — Three.js WebGL with orbit controls
- **Evidence with Calculation Sidebar** — RULA/REBA breakdown per frame
- **Click-to-Enlarge** — Lightbox modal for all evidence images

## Windows Installation

```cmd
cd C:\EUREKAI
python -m pip install flask mediapipe opencv-python numpy ultralytics
mkdir uploads outputs evidence
python app.py
```

First run auto-downloads:
- MediaPipe Pose model (~10MB)
- YOLOv8-nano model (~6MB)

Then open http://localhost:5000

## File Structure

```
eurekai_v5/
  app.py              — Flask web server
  config.py           — App configuration
  database.py         — SQLite storage
  workers.py          — Background processing pipeline
  requirements.txt    — Python dependencies
  README.md           — This file
  engines/
    __init__.py
    score_engine.py   — Official RULA/REBA scoring
    pose_engine.py    — MediaPipe pose detection
    video_engine.py   — Video processing, evidence capture
    activity_engine.py — Activity recognition
    knowledgebase.py  — Activity-specific recommendations
    lens_engine.py    — Three-lens registry
    yolo_engine.py    — YOLO object detection (NEW in v5)
    interaction_engine.py — Push/pull/carry/lift (NEW in v5)
  templates/
    base.html           — EUREKAI design system
    upload.html         — Video upload
    analysis.html       — Results page with evidence sidebar
    webcam.html         — Real-time webcam
    3d_viewer.html      — Interactive 3D skeleton
    history.html        — Past analyses
  static/images/
    eurekai-logo.png
```

## Scoring Reference

| RULA Score | Action |
|------------|--------|
| 1-2 | Negligible |
| 3-4 | Low — investigate and change soon |
| 5-6 | Medium — investigate and change shortly |
| 7 | High — implement change immediately |

| REBA Score | Risk Level |
|------------|-----------|
| 1 | Negligible |
| 2-3 | Low |
| 4-7 | Medium |
| 8-10 | High |
| 11-13 | Very High |
| 14+ | Extremely High |

## Interaction Detection

| Action | Detected From |
|--------|--------------|
| Push | Forward body lean + arms extended |
| Pull | Backward lean + arms pulling in |
| Carry | Upright posture + arms bent holding |
| Lift | Hands below waist + reaching down |
| Reach | Arms overhead |

## Object Detection

Detects: person, box/carton, cart, trolley, pallet, shelf/rack, door/gate, conveyor, forklift, bag, container, truck, backpack, suitcase, laptop, phone, and more.
