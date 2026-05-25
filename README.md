# Auty — Friendly Vision

Real-time facial recognition with multi-face tracking, ArcFace identity matching, a live MJPEG feed, and a React dashboard. The Python backend runs the vision pipeline; the browser UI shows live video, profiles, logs, and alerts.

**License:** [Apache-2.0](LICENSE) · SPDX-License-Identifier: Apache-2.0

## Features

- Live webcam feed with face detection, tracking, and recognition
- Enrollment flow for unknown visitors (name, age, status)
- HUD profile cards and screen effects
- Event bus + 6-state AI FSM (`IDLE` → `DETECTING` → `RECOGNIZED` / `UNKNOWN` → `ENGAGED`)
- Multi-step greeting sequences, attention on primary face, response throttling
- Optional TTS and voice commands; optional Ollama conversation (local only)
- All biometric data stays on disk under `data/` (not committed to git)

## Tech stack

| Layer | Technology |
|-------|------------|
| Vision | OpenCV, Haar + KCF/CSRT tracking |
| Identity | DeepFace (ArcFace embeddings) |
| Alignment | MediaPipe Face Mesh (optional fallback crop) |
| API | FastAPI, uvicorn, WebSocket |
| UI | React, Vite, Tailwind CSS, Framer Motion |
| Stream | MJPEG + WebSocket track metadata |
| HUD (optional) | Pillow overlays on server stream |
| AI behavior | Custom event system, state machine, response engine |
| Voice (optional) | pyttsx3, SpeechRecognition, sounddevice |
| LLM (optional) | Ollama HTTP API (localhost) |

## Screenshots

Add demo images to [`assets/screenshots/`](assets/screenshots/) before publishing.

## Installation

Requires **Python 3.11+** and a working webcam.

```bash
git clone <your-repo-url>
cd Auty
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Optional voice:
pip install -r requirements-voice.txt
```

**macOS notes**

- First DeepFace run downloads model weights.
- TensorFlow 2.21+ may need `tf-keras` (included in requirements).
- For PyAudio issues with voice, use `sounddevice` (already in optional requirements).

## First run

**Terminal 1 — API (port 8000):**

```bash
cp config/settings.example.json data/settings.json
pip install -r requirements.txt
python3 main.py
```

**Terminal 2 — React dashboard (port 5173):**

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). Vite proxies `/api` to the Python server.

**Production (single port):** `cd frontend && npm run build`, then start `python3 main.py` — FastAPI serves `frontend/dist` when present.

On first launch, any existing `face_db.pkl` / `profiles.json` at the repo root are **copied** into `data/` (originals left in place).

Environment overrides:

- `AUTY_DATA_DIR` — runtime data folder (default: `./data`)
- `AUTY_CONFIG` — settings file path (default: `./data/settings.json`)

## Usage

- **Recognized users** — appear with a green HUD card; Auty may greet once per session (cooldown configurable).
- **Unknown face** — enrollment panel opens; save a profile or skip.
- **Dashboard** — live feed, primary profile card, FSM state and mood.
- **Logs / Alerts / Profiles / Settings** — session timeline, unknown alerts, enrolled people, toggles.
- **Build DB offline** — place photos in `scripts/profile_sources/`, then `python3 scripts/build_db.py`.

## Project structure

```
Auty/
├── main.py                 # Starts FastAPI on :8000
├── server/                 # VisionEngine + REST + MJPEG + WebSocket
├── frontend/               # Vite React dashboard
├── config/                 # settings.example.json (committed)
├── data/                   # Local DB, profiles, captures (gitignored)
├── legacy/tk/             # Archived Tkinter UI (reference)
├── docs/                   # Architecture, setup, pipeline
├── scripts/                # build_db.py, legacy experiments
└── *.py                    # Core vision modules (unchanged)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the event pipeline.

## Documentation

- [docs/SETUP.md](docs/SETUP.md) — install and configuration
- [docs/PIPELINE.md](docs/PIPELINE.md) — frame loop and recognition flow
- [docs/ENROLLMENT.md](docs/ENROLLMENT.md) — enrolling new people
- [docs/DATABASE.md](docs/DATABASE.md) — `face_db.pkl`, profiles, memory

## Privacy

Auty processes video **locally**. Face embeddings and photos are stored under `data/`. Do not commit `data/` or share it publicly. You are responsible for consent and compliance when recognizing individuals.

## Roadmap

- [ ] `src/auty` package layout with `python -m auty`
- [ ] Stronger face detector (e.g. MediaPipe / YuNet) as default
- [ ] Automated tests for FSM and event bus
- [ ] CI (lint + smoke test)
- [ ] Optional Docker + Ollama compose for demos

## Legacy scripts

Early experiments live in [`scripts/legacy/`](scripts/legacy/) and are **not** used by the main app.
