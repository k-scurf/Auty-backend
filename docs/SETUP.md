# Setup

## Requirements

- Python 3.11+
- Webcam
- macOS, Linux, or Windows (tested primarily on macOS)

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional voice stack:

```bash
pip install -r requirements-voice.txt
```

## Configuration

1. Copy the example settings:

   ```bash
   mkdir -p data
   cp config/settings.example.json data/settings.json
   ```

2. Edit `data/settings.json` for camera index, thresholds, TTS, Ollama, etc.

Key sections:

| Section | Purpose |
|---------|---------|
| `confidence_threshold` / `min_lock_score` | Recognition matching |
| `insightface_pack` / `insightface_det_size` | InsightFace model pack and detect resolution |
| `face_detector` | `insightface` (default) or `haar` |
| `tracker_backend` | `bytetrack` (default) or OpenCV KCF via `tracker_type` |
| Pipeline tuning | See `config/pipeline.example.json` and `docs/PIPELINE_V2.md` |
| `use_face_alignment` / `alignment_backend` | RetinaFace 5-point warp before embed |
| `retinaface_detect_scale` | `0.75` = faster live detection (downscaled frame) |
| `detect_interval_frames` | Run detector every N frames (20 default with RetinaFace) |
| `async_recognition` | Offload ArcFace to background thread |
| `ai_states` / `behavior_timing` | FSM and presence timers |
| `behavior_throttle` | Greeting and voice cooldowns |
| `local_llm_enabled` | Ollama replies after greet |

## Data directory

Runtime files (gitignored):

| File | Purpose |
|------|---------|
| `data/face_db.pkl` | ArcFace embedding database |
| `data/profiles.json` | Display names, age, status |
| `data/memory.json` | Visit counts and social history |
| `data/captures/` | Enrollment photos |
| `data/logs.txt` | Recognition debug log |

Set `AUTY_DATA_DIR` to relocate all of the above.

## First launch migration

If you used an older layout with files at the repo root, Auty copies them into `data/` once (see console message). Verify recognition still works, then delete root copies if desired.

## Run (React dashboard)

**1. API server**

```bash
python3 main.py
```

Listens on `http://127.0.0.1:8000` (`/api/health`, `/api/stream.mjpg`, WebSocket `/api/ws`).

**2. Frontend (development)**

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The Vite dev server proxies `/api` to port 8000.

**Production:** build the frontend (`npm run build` in `frontend/`), then run `python3 main.py` only — static files are served from `frontend/dist/` when present.

## Legacy Tkinter UI

Archived under `legacy/tk/main_tk.py` (not the default entry point). See `legacy/tk/README.md`.

## Offline database build

```bash
mkdir -p scripts/profile_sources
# Add alice.jpg, bob_front.jpg, ...
python3 scripts/build_db.py
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `tf-keras` / Keras errors | `pip install tf-keras` |
| No camera | Check `camera_index` in settings |
| Slow feed | Ensure `async_recognition: true`, 960×540 processing |
| No TTS | `pip install pyttsx3`, `tts_enabled: true` |
| Multiple false boxes | Tune `use_strict_detection_filter`, `min_lock_score` |
