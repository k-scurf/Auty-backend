"""
FastAPI entry: MJPEG stream, WebSocket frame metadata, REST API.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from server.auty_engine import VisionEngine, get_engine
from server.schemas import (
    EnrollmentProgressOut,
    FrameSnapshotOut,
    HealthOut,
    ProfileCreate,
    ProfileOut,
    SettingsPatch,
)
from server.settings_loader import DEFAULT_SETTINGS, load_settings
from utils.paths import default_settings_path, ensure_directories

import database as db_mod

ensure_directories()

_vision: Optional[VisionEngine] = None
_vision_boot_started = False
_vision_boot_lock = threading.Lock()
_ws_interval = 1.0 / 12.0

_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
_INDEX = _DIST / "index.html"
_ASSETS = _DIST / "assets"

_DEV_HINT = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Auty API</title>
<style>body{font-family:system-ui;background:#0b0f14;color:#e2e8f0;max-width:36rem;margin:3rem auto;padding:0 1rem}
a{color:#2dd4bf}code{background:#1a222d;padding:.2em .4em;border-radius:4px}</style></head>
<body>
<h1>Auty API is running</h1>
<p>Build the dashboard, then <strong>restart</strong> <code>python main.py</code>:</p>
<pre>export PATH="/opt/homebrew/bin:$PATH"
cd frontend && npm install && npm run build</pre>
<p>Or run the dev server (keep this API running):</p>
<pre>./scripts/dev-frontend.sh</pre>
<p>Then open <a href="http://localhost:8000">http://localhost:8000</a> (after build)
or <a href="http://localhost:5173">http://localhost:5173</a> (dev only, while script runs).</p>
</body></html>"""


def _ui_built() -> bool:
    return _INDEX.is_file()


def _boot_vision_engine():
    """Load InsightFace and camera in a background thread so HTTP/WS accept immediately."""
    global _vision, _vision_boot_started
    with _vision_boot_lock:
        if _vision_boot_started:
            return
        _vision_boot_started = True

    def run():
        global _vision
        try:
            print(
                "[Auty] Starting vision engine (first run may download models; ~30–60s)…"
            )
            _vision = get_engine()
            print("[Auty] Vision engine ready")
        except Exception as exc:
            print(f"[Auty] Vision engine failed to start: {exc}")
            import traceback

            traceback.print_exc()

    threading.Thread(target=run, daemon=True, name="auty-vision-boot").start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _vision
    if _ui_built():
        print("[Auty] Dashboard: http://127.0.0.1:8000  (frontend/dist loaded)")
    else:
        print("[Auty] API only — build frontend/dist then restart, or run ./scripts/dev-frontend.sh")
    _boot_vision_engine()
    yield
    if _vision is not None:
        _vision.stop()


app = FastAPI(title="Auty API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_engine() -> VisionEngine:
    if vision_ref() is None:
        raise HTTPException(status_code=503, detail="Vision engine not started")
    return vision_ref()


def vision_ref() -> Optional[VisionEngine]:
    return _vision


@app.get("/api/health", response_model=HealthOut)
def health():
    eng = require_engine()
    h = eng.get_health()
    if not h["camera_ok"]:
        raise HTTPException(status_code=503, detail="Camera unavailable")
    return HealthOut(
        camera_ok=h["camera_ok"],
        db_loaded=h["db_loaded"],
        face_count=h["face_db_count"],
        profile_count=h["profile_count"],
        fps=h["fps"],
        uptime_seconds=h["uptime_seconds"],
        frame_count=h["frame_count"],
    )


@app.get("/api/health/status")
def health_soft():
    """Health without 503 — for status dots when camera warming up."""
    eng = vision_ref()
    if eng is None:
        return {
            "engine_ready": False,
            "camera_ok": False,
            "db_loaded": False,
            "face_count": 0,
            "profile_count": 0,
            "fps": 0.0,
            "uptime": 0.0,
            "frame_count": 0,
        }
    h = eng.get_health()
    return {
        "engine_ready": True,
        "camera_ok": h["camera_ok"],
        "db_loaded": h["db_loaded"],
        "face_count": h["face_db_count"],
        "profile_count": h["profile_count"],
        "fps": h["fps"],
        "uptime": h["uptime_seconds"],
        "frame_count": h["frame_count"],
    }


async def _mjpeg_generator():
    boundary = b"--frame"
    while True:
        eng = vision_ref()
        if eng is None:
            await asyncio.sleep(0.1)
            continue
        jpeg = eng.get_jpeg()
        if jpeg:
            yield boundary + b"\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        await asyncio.sleep(0.033)


@app.get("/api/stream.mjpg")
async def stream_mjpeg():
    eng = vision_ref()
    if eng is None:
        raise HTTPException(status_code=503, detail="Engine not ready")
    return StreamingResponse(
        _mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


_PLACEHOLDER_JPEG: bytes | None = None


def _placeholder_jpeg() -> bytes:
    global _PLACEHOLDER_JPEG
    if _PLACEHOLDER_JPEG is None:
        import cv2
        import numpy as np

        img = np.zeros((540, 960, 3), dtype=np.uint8)
        cv2.putText(
            img,
            "Starting camera…",
            (300, 280),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (148, 163, 184),
            2,
            cv2.LINE_AA,
        )
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        _PLACEHOLDER_JPEG = buf.tobytes() if ok else b""
    return _PLACEHOLDER_JPEG


@app.get("/api/frame.jpg")
def frame_jpeg():
    """Latest composited frame — works in all browsers (unlike MJPEG in <img>)."""
    eng = vision_ref()
    if eng is None:
        return Response(
            content=_placeholder_jpeg(),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )
    jpeg = eng.get_jpeg()
    if not jpeg:
        return Response(
            content=_placeholder_jpeg(),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@app.websocket("/api/ws")
async def websocket_frames(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            eng = vision_ref()
            if eng is None:
                await ws.send_json(
                    {"type": "error", "message": "Engine not ready"}
                )
                await asyncio.sleep(1.0)
                continue
            snap = eng.get_snapshot()
            if not eng.get_health()["camera_ok"]:
                await ws.send_json(
                    {"type": "error", "message": "Camera unavailable"}
                )
            else:
                await ws.send_json(snap.model_dump())
            await asyncio.sleep(_ws_interval)
    except WebSocketDisconnect:
        pass


@app.get("/api/logs")
def get_logs():
    eng = require_engine()
    return [e.model_dump() for e in eng.session_log.list_all()]


@app.get("/api/alerts")
def get_alerts():
    eng = require_engine()
    return [e.model_dump() for e in eng.session_log.alerts()]


@app.get("/api/profiles", response_model=list[ProfileOut])
def list_profiles():
    eng = require_engine()
    data = eng.db.load_profiles()
    out = []
    for name, p in data.items():
        rec = eng.db.store.find_by_name(name)
        out.append(
            ProfileOut(
                id=rec.id if rec else p.get("id"),
                name=p.get("name", name),
                age=str(p.get("age", "")),
                status=str(p.get("status", "")),
                image=p.get("image"),
                enrolled_at=rec.enrolled_at if rec else None,
            )
        )
    return out


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: str):
    eng = require_engine()
    prof = eng.db.get_profile_by_id(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    eng.db.delete_profile(name=prof.get("name"), rec_id=profile_id)
    return {"ok": True}


@app.post("/api/enrollment/start")
def enrollment_start(track_id: int | None = None):
    eng = require_engine()
    if not eng.start_guided_enrollment(track_id):
        raise HTTPException(status_code=400, detail="No face to enroll")
    return {"ok": True}


@app.get("/api/enrollment/status", response_model=EnrollmentProgressOut)
def enrollment_status():
    eng = require_engine()
    return eng.enrollment_progress()


@app.post("/api/enrollment/cancel")
def enrollment_cancel():
    eng = require_engine()
    eng.cancel_guided_enrollment()
    return {"ok": True}


@app.get("/api/profiles/{name}")
def get_profile(name: str):
    eng = require_engine()
    p = eng.db.get_profile(name)
    if not p:
        raise HTTPException(status_code=404, detail="Profile not found")
    return ProfileOut(
        name=p.get("name", name),
        age=str(p.get("age", "")),
        status=str(p.get("status", "")),
        image=p.get("image"),
    )


@app.get("/api/profiles/{name}/photo")
def profile_photo(name: str):
    eng = require_engine()
    p = eng.db.get_profile(name)
    if not p:
        raise HTTPException(status_code=404, detail="Profile not found")
    path = p.get("image")
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Photo not found")
    return FileResponse(path, media_type="image/jpeg")


@app.post("/api/profiles")
def create_profile(body: ProfileCreate):
    eng = require_engine()
    ok, msg = eng.save_profile(
        body.name, body.age, body.status, image_b64=body.image_b64
    )
    if not ok:
        print(f"[Auty] POST /api/profiles rejected: {msg}")
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "name": msg}


@app.post("/api/enrollment/skip")
def skip_enrollment():
    eng = require_engine()
    eng.skip_enrollment()
    return {"ok": True}


@app.get("/api/settings")
def get_settings():
    eng = require_engine()
    return eng.settings


@app.patch("/api/settings")
def patch_settings(body: SettingsPatch):
    eng = require_engine()
    allowed = set(DEFAULT_SETTINGS.keys())
    updates = {k: v for k, v in body.settings.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid keys to update")
    merged = {**eng.settings, **updates}
    path = default_settings_path()
    with open(path, "w") as f:
        json.dump(
            {k: merged[k] for k in merged if k not in ("memory_file", "log_file")},
            f,
            indent=2,
        )
    eng.settings = load_settings()
    import recognition as rec
    from vision import config as vcfg

    rec.configure(eng.settings)
    vcfg.configure(eng.settings)
    eng._emotion_enabled = bool(eng.settings.get("user_emotion_enabled", False))
    eng.emotion_analyzer = __import__(
        "user_emotion", fromlist=["UserEmotionAnalyzer"]
    ).UserEmotionAnalyzer(eng.settings)
    re = eng.response_engine
    re.greetings_enabled = bool(eng.settings.get("greetings_enabled", False))
    re.personality_enabled = bool(eng.settings.get("personality_enabled", False))
    re.greeting_bar_enabled = bool(eng.settings.get("greeting_bar_enabled", False))
    return eng.settings


if _ASSETS.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_ASSETS)), name="frontend-assets")


@app.get("/")
def root():
    if _ui_built():
        return FileResponse(_INDEX, media_type="text/html")
    return HTMLResponse(_DEV_HINT)


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    """React Router paths (e.g. /logs) — serve index.html when UI is built."""
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    if _ui_built():
        return FileResponse(_INDEX, media_type="text/html")
    raise HTTPException(status_code=404, detail="UI not built")


def _shutdown_handler(signum, frame):
    eng = vision_ref()
    if eng:
        eng.stop()
    raise SystemExit(0)


signal.signal(signal.SIGINT, _shutdown_handler)
signal.signal(signal.SIGTERM, _shutdown_handler)
