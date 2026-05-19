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

## Run

```bash
python3 main.py
```

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
