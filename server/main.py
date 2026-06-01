"""
FastAPI entry: MJPEG stream, WebSocket frame metadata, REST API.
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

_src = _Path(__file__).resolve().parents[1] / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

import asyncio
import base64
import collections
import datetime as dt
import hmac
import io
import json
import logging
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
import uuid
from typing import Optional
from zoneinfo import ZoneInfo

import cv2
import numpy as np

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from camera import local_camera_enabled
from server.auty_engine import VisionEngine, get_engine
from server.schemas import (
    AttendanceEventOut,
    AttendanceNoteCreate,
    AttendanceStatusOut,
    ConsentCreate,
    ConsentStatusOut,
    EnrollmentProgressOut,
    ExportPreviewOut,
    ExportRequest,
    FrameCheckOut,
    FrameCheckRequest,
    FrameSnapshotOut,
    HealthOut,
    LoginRequest,
    LoginResponse,
    TenantCreate,
    TenantCreatedOut,
    PresenceOut,
    ProfileCreate,
    ProfileOut,
    SettingsPatch,
    TodayAttendanceStatusOut,
    WeeklyScheduleIn,
    WeeklyScheduleOut,
)
from server.settings_loader import DEFAULT_SETTINGS, load_settings
from utils.paths import default_settings_path, ensure_directories

from attendance_schedules import DEFAULT_TZ, DAYS, ScheduleStore, normalize_schedule
import database as db_mod
from payroll_export import (
    build_export_csv,
    build_export_csv_from_events,
    compute_preview,
    compute_preview_from_events,
)

ensure_directories()

from auty.auth import optional_tenant, require_tenant  # noqa: E402

# Fix #9: maximum bytes accepted for any uploaded or base64-encoded image
MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB

# Fix #8: simple in-memory rate limiter for the login endpoint
_LOGIN_RATE_WINDOW = 300   # seconds
_LOGIN_RATE_MAX = 10       # attempts per window per IP
_login_lock = threading.Lock()
_login_attempts: dict[str, list[float]] = collections.defaultdict(list)


def _check_login_rate(ip: str) -> None:
    now = time.time()
    cutoff = now - _LOGIN_RATE_WINDOW
    with _login_lock:
        attempts = [t for t in _login_attempts[ip] if t > cutoff]
        if len(attempts) >= _LOGIN_RATE_MAX:
            raise HTTPException(
                status_code=429,
                detail="Too many login attempts — please wait before trying again.",
                headers={"Retry-After": str(_LOGIN_RATE_WINDOW)},
            )
        attempts.append(now)
        _login_attempts[ip] = attempts


def _safe_filename_part(s: str) -> str:
    """Fix #12: strip characters that could inject into Content-Disposition headers."""
    return re.sub(r"[^A-Za-z0-9_\-]", "_", str(s))[:40]


def _pg_enabled() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def _open_db():
    from auty.db.connection import get_session_factory

    return get_session_factory()()


def _sync_profile_to_db(
    tenant_id: uuid.UUID, name: str, age: str, status: str, image_path: Optional[str] = None
) -> None:
    from auty.db import repositories as repo

    employee_id: Optional[uuid.UUID] = None
    eng = vision_ref()
    if eng is not None:
        identity = eng.db.store.find_by_name(name)
        if identity:
            try:
                employee_id = uuid.UUID(str(identity.id))
            except ValueError:
                employee_id = None

    db = _open_db()
    try:
        row = repo.get_employee_by_name(db, tenant_id, name)
        if row is None:
            repo.create_employee(
                db,
                tenant_id,
                name=name,
                age=age,
                status=status,
                photo_path=image_path,
                employee_id=employee_id,
            )
        else:
            repo.update_employee(
                db,
                tenant_id,
                row.id,
                name=name,
                age=age,
                status=status,
                photo_path=image_path or row.photo_path,
            )
    finally:
        db.close()


class _QuietFrameAccessLog(logging.Filter):
    _SUPPRESS = ("/api/frame.jpg", "/api/attendance/active", "/api/health/status", "/api/camera/check-frame")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(s in msg for s in self._SUPPRESS)


logging.getLogger("uvicorn.access").addFilter(_QuietFrameAccessLog())

_vision: Optional[VisionEngine] = None
_vision_boot_started = False
_vision_boot_lock = threading.Lock()
_ws_interval = 1.0 / 12.0

_DEFAULT_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
_DIST = Path(os.environ.get("AUTY_FRONTEND_DIST", str(_DEFAULT_DIST))).expanduser().resolve()
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


def _defer_vision_boot() -> bool:
    if os.environ.get("AUTY_DEFER_VISION_BOOT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return True
    return bool(os.environ.get("RAILWAY_ENVIRONMENT"))


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
    global _vision, _INDEX_BYTES
    # Additive PostgreSQL init; file-based storage remains until migration Phase 5.
    if os.environ.get("DATABASE_URL"):
        from auty.db.bootstrap import ensure_default_tenant
        from auty.db.connection import get_session_factory
        from auty.db.init_db import create_all_tables

        create_all_tables()
        db = get_session_factory()()
        try:
            ensure_default_tenant(db)
        finally:
            db.close()
        print("[Auty] PostgreSQL tables ready")
    else:
        print("[Auty] DATABASE_URL not set — skipping PostgreSQL init")
    if _ui_built():
        _INDEX_BYTES = _INDEX.read_bytes()
        url = "http://127.0.0.1:8000"
        print(f"[Auty] Dashboard: {url}  ({_DIST} loaded)")
        print("[Auty] Live camera feed is in the browser — no separate preview window.")
        if os.environ.get("AUTY_NO_BROWSER", "").lower() not in ("1", "true", "yes"):

            def _open_browser():
                import time
                import webbrowser

                time.sleep(1.2)
                webbrowser.open(url)

            threading.Thread(target=_open_browser, daemon=True).start()
    else:
        print(f"[Auty] API only — frontend dist not found at {_DIST}")
        if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("AUTY_HEADLESS"):
            print(
                "[Auty] Cloud deploy: serve the dashboard from Vercel; "
                "this service is API-only (no server webcam)."
            )
        else:
            print("[Auty] Then open http://127.0.0.1:8000 — or run: cd frontend && npm run dev")
    if _defer_vision_boot():
        print(
            "[Auty] Vision engine deferred — loads on first API use "
            "(buffalo_sc on Railway to limit memory)."
        )
    else:
        _boot_vision_engine()
    yield
    if _vision is not None:
        print("[Auty] Shutting down vision engine…")
        _vision.stop()
        print("[Auty] Shutdown complete")


app = FastAPI(title="Auty API", version="1.0.0", lifespan=lifespan)

# Fix #7: allow_credentials=True with a broad LAN regex lets any page on the
# local network make credentialed cross-origin requests.  Auth uses Bearer
# tokens (not cookies), so credentials=False is safe and closes the CSRF risk.
# Operators can add extra origins via AUTY_EXTRA_ORIGINS (comma-separated).
_CORS_ORIGINS = [
    "https://auty.app",
    "https://www.auty.app",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]
_extra = [o.strip() for o in os.environ.get("AUTY_EXTRA_ORIGINS", "").split(",") if o.strip()]
_CORS_ORIGINS.extend(_extra)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_origin_regex=r"https?://192\.168\.\d+\.\d+(:\d+)?",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_engine() -> VisionEngine:
    global _vision
    if _vision is None:
        _vision = get_engine()
    return _vision


def vision_ref() -> Optional[VisionEngine]:
    return _vision


@app.post("/api/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request):
    # Fix #8: rate-limit before doing any credential work
    client_ip = request.client.host if request.client else "unknown"
    _check_login_rate(client_ip)

    if os.environ.get("DATABASE_URL"):
        from auty.auth import authenticate_tenant, create_jwt
        from auty.db.connection import get_session_factory

        db = get_session_factory()()
        try:
            tenant = authenticate_tenant(db, body.username, body.password)
            if tenant is None:
                raise HTTPException(
                    status_code=401, detail="Incorrect username or password"
                )
            token, expires_at_dt = create_jwt(tenant.id, tenant.username)
            expires_at = expires_at_dt.isoformat().replace("+00:00", "Z")
            return LoginResponse(token=token, expires_at=expires_at)
        finally:
            db.close()

    # Legacy file-based auth (local-only mode; no DB)
    settings = load_settings()
    expected_username = str(
        os.environ.get("AUTY_MANAGER_USERNAME")
        or settings.get("manager_username")
        or "owner"
    )
    expected_password = str(
        os.environ.get("AUTY_MANAGER_PASSWORD")
        or settings.get("manager_password")
        or settings.get("kiosk_pin")
        or "1234"
    )

    # Fix #10: constant-time comparison to prevent timing attacks
    username_ok = hmac.compare_digest(body.username.strip(), expected_username)
    password_ok = hmac.compare_digest(body.password, expected_password)
    if not username_ok or not password_ok:
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    # Fix #5: issue a properly signed JWT (was an unverifiable random string)
    from auty.auth import create_jwt as _create_jwt
    _local_tenant_id = uuid.UUID(int=0)
    token, expires_at_dt = _create_jwt(_local_tenant_id, expected_username)
    expires_at = expires_at_dt.isoformat().replace("+00:00", "Z")
    return LoginResponse(token=token, expires_at=expires_at)


@app.post("/api/admin/tenants", response_model=TenantCreatedOut)
def admin_create_tenant(
    body: TenantCreate,
    admin_secret: str = Header(..., alias="admin-secret"),
):
    if not os.environ.get("DATABASE_URL"):
        raise HTTPException(status_code=503, detail="Database not configured")

    from auty.auth import hash_password, verify_admin_secret
    from auty.db.connection import get_session_factory
    from auty.db.models import Tenant
    from sqlalchemy import select

    verify_admin_secret(admin_secret)

    username = body.username.strip()
    if not username or not body.password:
        raise HTTPException(status_code=400, detail="username and password are required")

    db = get_session_factory()()
    try:
        if db.scalar(select(Tenant.id).where(Tenant.username == username)):
            raise HTTPException(status_code=409, detail="Username already exists")
        tenant = Tenant(
            name=(body.name or username).strip(),
            username=username,
            password_hash=hash_password(body.password),
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return TenantCreatedOut(id=str(tenant.id), username=tenant.username)
    finally:
        db.close()


@app.get("/api/health/live")
def health_live():
    """Lightweight probe for Railway/load balancers — never loads models."""
    return {"ok": True, "vision_loaded": vision_ref() is not None}


@app.get("/api/health", response_model=HealthOut)
def health():
    eng = vision_ref()
    if eng is None:
        return HealthOut(
            camera_ok=True,
            db_loaded=False,
            face_count=0,
            profile_count=0,
            fps=0.0,
            uptime_seconds=0.0,
            frame_count=0,
        )
    h = eng.get_health()
    if not h["camera_ok"] and local_camera_enabled(eng.settings):
        raise HTTPException(status_code=503, detail="Camera unavailable")
    camera_ok = h["camera_ok"] or not local_camera_enabled(eng.settings)
    return HealthOut(
        camera_ok=camera_ok,
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
    h = eng.get_health_light()
    return {
        "engine_ready": True,
        "camera_ok": h["camera_ok"],
        "db_loaded": h["db_loaded"],
        "face_count": h["face_count"],
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
        # Offload the threading.Lock acquisition to a thread to avoid stalling uvloop.
        jpeg = await asyncio.to_thread(eng.get_jpeg)
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


_PLACEHOLDER_CACHE: dict[str, bytes] = {}
_INDEX_BYTES: Optional[bytes] = None
_INDEX_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


def _index_bytes() -> bytes:
    global _INDEX_BYTES
    if _INDEX_BYTES is None:
        _INDEX_BYTES = _INDEX.read_bytes()
    return _INDEX_BYTES


def _placeholder_jpeg(message: str = "Starting camera…") -> bytes:
    if message in _PLACEHOLDER_CACHE:
        return _PLACEHOLDER_CACHE[message]
    import cv2
    import numpy as np

    img = np.zeros((540, 960, 3), dtype=np.uint8)
    cv2.putText(
        img,
        message[:48],
        (80, 260),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.85,
        (148, 163, 184),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        img,
        "Open http://127.0.0.1:8000 for live feed",
        (200, 320),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (100, 116, 139),
        1,
        cv2.LINE_AA,
    )
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    result = buf.tobytes() if ok else b""
    _PLACEHOLDER_CACHE[message] = result
    return result


def _frame_jpeg_bytes() -> bytes:
    """Keep this fast — runs under heavy /api/frame.jpg load."""
    eng = vision_ref()
    if eng is None:
        return _placeholder_jpeg("Starting camera…")
    jpeg = eng.get_jpeg()
    if not jpeg:
        return _placeholder_jpeg("Starting camera…")
    return jpeg


@app.get("/api/frame.jpg")
def frame_jpeg():
    """Latest composited frame — works in all browsers (unlike MJPEG in <img>)."""
    return Response(
        content=_frame_jpeg_bytes(),
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
                await ws.send_json({"type": "status", "ready": False})
                await asyncio.sleep(1.0)
                continue
            # Run get_ws_broadcast() in a thread so the threading.Lock acquisition
            # and any Pydantic model_dump() work never blocks the uvloop event thread.
            payload = await asyncio.to_thread(eng.get_ws_broadcast)
            await ws.send_json(payload)
            await asyncio.sleep(_ws_interval)
    except WebSocketDisconnect:
        pass
    except RuntimeError:
        # send/receive on a closed WebSocket raises RuntimeError in Starlette
        pass
    except Exception:
        pass


@app.get("/api/presence", response_model=PresenceOut)
def get_presence():
    eng = vision_ref()
    if eng is None:
        return PresenceOut()
    return eng.get_presence()


@app.get("/api/logs")
def get_logs():
    eng = require_engine()
    return [e.model_dump() for e in eng.session_log.list_all()]


@app.get("/api/alerts")
def get_alerts():
    eng = require_engine()
    return [e.model_dump() for e in eng.session_log.alerts()]


@app.get("/api/profiles", response_model=list[ProfileOut])
def list_profiles(tenant_id: Optional[uuid.UUID] = Depends(require_tenant)):
    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            return [ProfileOut(**p) for p in repo.list_employees(db, tenant_id)]
        finally:
            db.close()
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
def delete_profile(
    profile_id: str,
    tenant_id: Optional[uuid.UUID] = Depends(require_tenant),
):
    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        eid: Optional[uuid.UUID] = None
        try:
            try:
                eid = uuid.UUID(profile_id)
            except ValueError:
                eid = None
            deleted = False
            if eid is not None:
                row = repo.get_employee_by_id(db, tenant_id, eid)
                if row:
                    repo.delete_employee(db, tenant_id, eid)
                    deleted = True
                    profile_id = row.name
            if not deleted:
                deleted = repo.delete_employee_by_name(db, tenant_id, profile_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="Profile not found")
        finally:
            db.close()
        eng = require_engine()
        eng.db.delete_profile(name=profile_id, rec_id=str(eid) if eid else None)
        from auty.db.embedding_store import invalidate_tenant_gallery

        invalidate_tenant_gallery(tenant_id)
        return {"ok": True}

    eng = require_engine()
    prof = eng.db.get_profile_by_id(profile_id)
    if prof:
        eng.db.delete_profile(name=prof.get("name"), rec_id=profile_id)
        return {"ok": True}
    if eng.db.get_profile(profile_id):
        eng.db.delete_profile(name=profile_id)
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Profile not found")


@app.post("/api/recognize-frame", response_model=FrameSnapshotOut)
async def recognize_frame(
    file: UploadFile = File(...),
    tenant_id: Optional[uuid.UUID] = Depends(optional_tenant),
):
    """Accept a JPEG from a client device camera (e.g. iPad), run face
    recognition, fire clock-in/out if appropriate, and return a FrameSnapshotOut.
    This endpoint powers the iPad camera path where getUserMedia captures frames
    that are sent here for server-side InsightFace recognition.
    """
    eng = require_engine()
    jpeg_bytes = await file.read()
    # Fix #9: reject oversized uploads before decoding to prevent OOM DoS
    if len(jpeg_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large")
    face_db = None
    if tenant_id is not None:
        db = _open_db()
        try:
            from auty.db.embedding_store import load_tenant_gallery

            face_db = load_tenant_gallery(db, tenant_id)
        finally:
            db.close()
    import asyncio

    snapshot = await asyncio.to_thread(eng.recognize_client_frame, jpeg_bytes, face_db)
    return snapshot


@app.post("/api/profiles/reset-all")
def reset_all_profiles(tenant_id: Optional[uuid.UUID] = Depends(require_tenant)):
    """Delete every identity record, face embedding, and profile. Cannot be undone."""
    eng = require_engine()

    if tenant_id is not None:
        from auty.db import repositories as repo
        from auty.db.embedding_store import invalidate_tenant_gallery

        db = _open_db()
        employee_ids: list[str] = []
        try:
            employee_ids = [p["id"] for p in repo.list_employees(db, tenant_id)]
            repo.reset_tenant_data(db, tenant_id)
        finally:
            db.close()
        invalidate_tenant_gallery(tenant_id)

        for eid in employee_ids:
            eng.db.store.delete(str(eid))
        profiles = eng.db.load_profiles()
        for eid in employee_ids:
            prof = eng.db.get_profile_by_id(eid)
            if prof and prof.get("name") in profiles:
                profiles.pop(prof["name"], None)
        with open(db_mod.PROFILE_DB, "w") as f:
            json.dump(profiles, f, indent=4)
        eng.db._profiles_cache = profiles
        eng.db.face_db = eng.db.store.build_face_db()
        eng.db.save()
    else:
        # ── Legacy: full file store reset (no PostgreSQL tenant) ─────────────
        eng.db.reset(clear_captures=True)

    # ── 2. Truncate attendance log (zero it out so _load_state_from_log
    #        won't re-populate stale data on next start) ────────────────────
    att_log = str(eng.settings.get("attendance_log_path", "data/attendance_log.jsonl"))
    att_notes = str(eng.settings.get("attendance_notes_path", "data/attendance_notes.json"))
    try:
        open(att_log, "w").close()
    except OSError:
        pass
    try:
        with open(att_notes, "w") as f:
            f.write("{}")
    except OSError:
        pass

    # ── 3. Clear presence sessions file ──────────────────────────────────
    pres_path = str(eng.settings.get("presence_sessions_path", "data/presence_sessions.json"))
    try:
        with open(pres_path, "w") as f:
            f.write("{}")
    except OSError:
        pass

    # ── 4. Flush all in-memory state ─────────────────────────────────────
    eng.track_manager.reset()
    eng.attendance_tracker.reset()
    eng.presence_tracker.reset()
    eng._kiosk_last_action.clear()
    if hasattr(eng, "_kiosk_acted_track_ids"):
        eng._kiosk_acted_track_ids.clear()
    eng.session_log.clear()
    eng._enrollment["auto_committed"] = False
    eng._enrollment["provisional_name"] = None
    from vision.matcher import sync_gallery
    sync_gallery(eng.db.face_db, eng.db.store)
    return {"ok": True}


@app.post("/api/enrollment/start")
def enrollment_start(track_id: int | None = None):
    eng = require_engine()
    if not eng.start_guided_enrollment(track_id):
        raise HTTPException(
            status_code=400,
            detail="No face detected — center your face in the camera and hold still",
        )
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
def get_profile(name: str, tenant_id: Optional[uuid.UUID] = Depends(require_tenant)):
    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            row = repo.get_employee_by_name(db, tenant_id, name)
            if row is None:
                raise HTTPException(status_code=404, detail="Profile not found")
            return ProfileOut(
                id=str(row.id),
                name=row.name,
                age=row.age or "",
                status=row.status or "",
                image=row.photo_path,
                enrolled_at=row.enrolled_at.isoformat() if row.enrolled_at else None,
            )
        finally:
            db.close()

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


def _safe_photo_response(path: str) -> "FileResponse":
    """Fix #16: resolve path and verify it lives inside DATA_DIR before serving."""
    from utils.paths import DATA_DIR as _DATA_DIR

    try:
        resolved = Path(path).resolve()
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Photo not found")
    if not resolved.is_relative_to(_DATA_DIR):
        raise HTTPException(status_code=404, detail="Photo not found")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Photo not found")
    return FileResponse(str(resolved), media_type="image/jpeg")


@app.get("/api/profiles/{name}/photo")
def profile_photo(name: str, tenant_id: Optional[uuid.UUID] = Depends(require_tenant)):
    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            row = repo.get_employee_by_name(db, tenant_id, name)
            if row is None or not row.photo_path:
                raise HTTPException(status_code=404, detail="Photo not found")
            path = row.photo_path
        finally:
            db.close()
        return _safe_photo_response(path)

    eng = require_engine()
    p = eng.db.get_profile(name)
    if not p:
        raise HTTPException(status_code=404, detail="Profile not found")
    path = p.get("image")
    if not path:
        raise HTTPException(status_code=404, detail="Photo not found")
    return _safe_photo_response(path)


def _classify_save_error(msg: str) -> str:
    """Map a save_profile error string to a structured error code."""
    m = msg.lower()
    if msg.startswith("MULTIPLE_FACES:"):
        return "MULTIPLE_FACES"
    if msg.startswith("NO_FACE_DETECTED:"):
        return "NO_FACE_DETECTED"
    if msg.startswith("LOW_CONFIDENCE:"):
        return "LOW_CONFIDENCE"
    if "name is required" in m:
        return "INVALID_INPUT"
    if "no face ready" in m:
        return "NO_FACE_READY"
    if "could not generate embedding" in m or "check lighting" in m:
        return "NO_FACE_DETECTED"
    if "could not rename" in m:
        return "RENAME_FAILED"
    if "already enrolled" in m or "duplicate" in m:
        return "ALREADY_ENROLLED"
    if "consent" in m:
        return "CONSENT_MISSING"
    if "enrollment failed" in m:
        return "ENROLLMENT_FAILED"
    return "MODEL_ERROR"


def _action_for_code(code: str) -> str:
    return {
        "NO_FACE_DETECTED": "retake",
        "MULTIPLE_FACES": "retake",
        "NO_FACE_READY": "retake_all",
        "LOW_CONFIDENCE": "retake_all",
        "INVALID_INPUT": "fix_input",
        "RENAME_FAILED": "retry",
        "ALREADY_ENROLLED": "view_existing",
        "CONSENT_MISSING": "restart",
        "ENROLLMENT_FAILED": "retry",
        "MODEL_ERROR": "retry",
    }.get(code, "retry")


def _decode_b64_image(image_b64: str):
    """Return BGR numpy array or None."""
    try:
        payload = image_b64.strip()
        if "," in payload and payload.startswith("data:"):
            payload = payload.split(",", 1)[1]
        raw = base64.b64decode(payload)
        arr = np.frombuffer(raw, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _validate_enrollment_images(images: list) -> Optional[dict]:
    """Validate each submitted photo; return error detail dict or None."""
    from vision.detector import detect as _detect

    for i, img_b64 in enumerate(images):
        frame = _decode_b64_image(img_b64)
        if frame is None or frame.size == 0:
            return {
                "code": "NO_FACE_DETECTED",
                "message": f"No face detected in photo {i + 1}",
                "photo_index": i,
                "action": "retake",
            }
        faces = _detect(frame, max_faces=3)
        if len(faces) == 0:
            return {
                "code": "NO_FACE_DETECTED",
                "message": f"No face detected in photo {i + 1}",
                "photo_index": i,
                "action": "retake",
            }
        if len(faces) > 1:
            return {
                "code": "MULTIPLE_FACES",
                "message": (
                    f"Multiple faces detected in photo {i + 1}. "
                    "Only one person should be in frame."
                ),
                "photo_index": i,
                "action": "retake",
            }
    return None


@app.post("/api/profiles")
def create_profile(
    body: ProfileCreate,
    tenant_id: Optional[uuid.UUID] = Depends(require_tenant),
):
    eng = require_engine()

    # Device-camera 3-photo flow: first image is primary, rest add extra embeddings.
    primary_b64 = body.image_b64
    extra_images: Optional[list] = None
    if body.images:
        if len(body.images) != 3:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_INPUT",
                    "message": "Exactly 3 photos are required to enroll.",
                    "action": "retake_all",
                },
            )
        validation_err = _validate_enrollment_images(body.images)
        if validation_err:
            raise HTTPException(status_code=422, detail=validation_err)
        if not primary_b64:
            primary_b64 = body.images[0]
        if len(body.images) > 1:
            extra_images = body.images[1:]

    ok, msg = eng.save_profile(
        body.name, body.age, body.status,
        image_b64=primary_b64,
        extra_images=extra_images,
        allow_low_confidence=body.allow_low_confidence,
    )
    if not ok:
        code = _classify_save_error(msg)
        status = 422 if code in (
            "NO_FACE_DETECTED", "MULTIPLE_FACES", "LOW_CONFIDENCE", "ALREADY_ENROLLED"
        ) else 400
        detail = {"code": code, "message": msg, "action": _action_for_code(code)}
        if code == "LOW_CONFIDENCE" and ":" in msg:
            try:
                detail["confidence"] = float(msg.split(":")[-1])
            except ValueError:
                pass
        if code in ("NO_FACE_DETECTED", "MULTIPLE_FACES") and ":" in msg:
            try:
                detail["photo_index"] = int(msg.rsplit(":", 1)[-1])
            except ValueError:
                pass
        print(f"[Auty] POST /api/profiles rejected [{code}]: {msg}")
        raise HTTPException(status_code=status, detail=detail)
    if tenant_id is not None:
        prof = eng.db.get_profile(msg) or {}
        image_path = prof.get("image")
        if image_path and body.image_b64:
            from auty.db.repositories import tenant_photos_dir

            photos = tenant_photos_dir(tenant_id)
            identity = eng.db.store.find_by_name(msg)
            fname = f"{identity.id if identity else msg}.jpg"
            dest = photos / fname
            try:
                if os.path.isfile(image_path):
                    import shutil

                    shutil.copy2(image_path, dest)
                    image_path = str(dest)
            except OSError:
                pass
        _sync_profile_to_db(
            tenant_id,
            msg,
            body.age,
            body.status,
            image_path=image_path,
        )
        eng.persist_embeddings_to_postgres(tenant_id, msg)
    return {"ok": True, "name": msg}


@app.post("/api/camera/check-frame", response_model=FrameCheckOut)
def check_enrollment_frame(body: FrameCheckRequest):
    """
    Decode a base-64 JPEG sent from the device camera and return three quality
    signals used by the enrollment wizard to gate the Capture button.
    """
    from vision.insightface_app import models_ready as _models_ready
    from vision.detector import detect as _detect

    if not _models_ready():
        return FrameCheckOut(face_detected=False, message="models_loading")

    # Decode the image
    try:
        payload = body.image_b64.strip()
        if "," in payload and payload.startswith("data:"):
            payload = payload.split(",", 1)[1]
        # Fix #9: check estimated decoded size before allocating
        if len(payload) * 3 // 4 > MAX_IMAGE_BYTES:
            return FrameCheckOut(face_detected=False, message="image_too_large")
        raw = base64.b64decode(payload)
        arr = np.frombuffer(raw, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return FrameCheckOut(face_detected=False, message="decode_error")

    if frame is None or frame.size == 0:
        return FrameCheckOut(face_detected=False, message="empty_frame")

    fh, fw = frame.shape[:2]

    # Basic lighting check on the whole frame (fast path — no face required)
    gray_full = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    brightness_full = float(gray_full.mean())
    frame_lighting_ok = 55 <= brightness_full <= 225

    faces = _detect(frame, max_faces=3)
    if not faces:
        return FrameCheckOut(
            face_detected=False,
            face_count=0,
            lighting_ok=frame_lighting_ok,
            centered=False,
        )

    if len(faces) > 1:
        return FrameCheckOut(
            face_detected=False,
            face_count=len(faces),
            lighting_ok=frame_lighting_ok,
            centered=False,
            message="multiple_faces",
        )

    face = faces[0]
    x, y, w, h = face.bbox

    # Lighting: mean brightness of the face crop
    cx1, cy1 = max(0, x), max(0, y)
    cx2, cy2 = min(fw, x + w), min(fh, y + h)
    crop_gray = gray_full[cy1:cy2, cx1:cx2]
    brightness_face = float(crop_gray.mean()) if crop_gray.size > 0 else brightness_full
    lighting_ok = 55 <= brightness_face <= 225

    # Centering: face centre within 25 % of frame dimensions from frame centre
    face_cx = x + w / 2.0
    face_cy = y + h / 2.0
    dx = abs(face_cx - fw / 2.0) / fw
    dy = abs(face_cy - fh / 2.0) / fh
    centered = dx <= 0.25 and dy <= 0.25

    return FrameCheckOut(
        face_detected=True,
        face_count=len(faces),
        lighting_ok=lighting_ok,
        centered=centered,
    )


@app.post("/api/enrollment/skip")
def skip_enrollment():
    eng = require_engine()
    eng.skip_enrollment()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

_schedule_store = ScheduleStore()


def _employee_records(
    eng: VisionEngine, tenant_id: Optional[uuid.UUID] = None
) -> list[dict]:
    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            return [
                {"employee_id": p["id"], "name": p["name"]}
                for p in repo.list_employees(db, tenant_id)
            ]
        finally:
            db.close()

    profiles = eng.db.load_profiles()
    out: list[dict] = []
    for name, profile in profiles.items():
        rec = eng.db.store.find_by_name(name)
        employee_id = str(rec.id if rec else profile.get("id") or name)
        out.append(
            {
                "employee_id": employee_id,
                "name": str(profile.get("name") or name),
            }
        )
    return out


def _tz(name: str):
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def _local_time(date: dt.date, hhmm: str, tzinfo) -> dt.datetime:
    hour, minute = [int(part) for part in hhmm.split(":", 1)]
    return dt.datetime.combine(date, dt.time(hour, minute), tzinfo=tzinfo)


def _format_ts(ts: Optional[float], tzinfo) -> Optional[str]:
    if ts is None:
        return None
    return dt.datetime.fromtimestamp(ts, tzinfo).strftime("%H:%M")


def _today_events_for_employee(events: list[dict], employee_id: str, name: str, today: dt.date, tzinfo) -> list[dict]:
    matched = []
    for ev in events:
        if str(ev.get("employee_id") or "") != employee_id and ev.get("name") != name:
            continue
        ts = float(ev.get("timestamp_ts") or 0.0)
        if dt.datetime.fromtimestamp(ts, tzinfo).date() == today:
            matched.append(ev)
    return sorted(matched, key=lambda e: float(e.get("timestamp_ts") or 0.0))


def _first_shift_pair(events: list[dict]) -> tuple[Optional[dict], Optional[dict]]:
    clock_in = None
    for ev in events:
        if ev.get("event") == "CLOCK_IN" and clock_in is None:
            clock_in = ev
        elif ev.get("event") == "CLOCK_OUT" and clock_in is not None:
            return clock_in, ev
    return clock_in, None


def _status_alert(status: str, name: str, minutes: int, shift_start: Optional[str], shift_end: Optional[str]) -> Optional[str]:
    if status == "late" and shift_start:
        return f"{name} is {minutes} minutes late (shift started at {shift_start})"
    if status == "missing_clockout" and shift_end:
        return f"{name} hasn't clocked out (shift ended at {shift_end})"
    if status == "absent":
        return f"{name} has not clocked in today"
    return None


@app.get("/api/schedules/{employee_id}", response_model=WeeklyScheduleOut)
def get_schedule(
    employee_id: str,
    tenant_id: Optional[uuid.UUID] = Depends(require_tenant),
):
    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            saved = repo.get_schedule(db, tenant_id, employee_id)
        finally:
            db.close()
        if not saved:
            raise HTTPException(status_code=404, detail="No schedule saved")
        return WeeklyScheduleOut(**saved)

    saved = _schedule_store.get(employee_id)
    if not saved:
        raise HTTPException(status_code=404, detail="No schedule saved")
    return WeeklyScheduleOut(**saved)


@app.post("/api/schedules/{employee_id}", response_model=WeeklyScheduleOut)
def save_schedule(
    employee_id: str,
    body: WeeklyScheduleIn,
    tenant_id: Optional[uuid.UUID] = Depends(require_tenant),
):
    data = body.model_dump()
    data["employee_id"] = employee_id

    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            saved = repo.save_schedule(db, tenant_id, employee_id, data)
        finally:
            db.close()
        _schedule_store.save(employee_id, data)  # legacy backup until Phase 5
        return WeeklyScheduleOut(**saved)

    saved = _schedule_store.save(employee_id, data)
    return WeeklyScheduleOut(**saved)


# ---------------------------------------------------------------------------
# Attendance routes
# ---------------------------------------------------------------------------

@app.get("/api/attendance/active")
def get_attendance_active(tenant_id: Optional[uuid.UUID] = Depends(require_tenant)):
    """Who is clocked in right now."""
    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            return repo.attendance_active_snapshot(db, tenant_id)
        finally:
            db.close()

    eng = vision_ref()
    if eng is None:
        return {"clocked_in": [], "recent_events": [], "alerts": []}
    tracker = eng.get_attendance_tracker()
    if tracker is None:
        return {"clocked_in": [], "recent_events": [], "alerts": []}
    return tracker.snapshot_dict()


@app.get("/api/attendance/status/today", response_model=TodayAttendanceStatusOut)
def get_today_attendance_status(
    tenant_id: Optional[uuid.UUID] = Depends(require_tenant),
):
    """Every employee's schedule-aware attendance status for today."""
    eng = require_engine()
    tracker = eng.get_attendance_tracker()
    if tracker is None and tenant_id is None:
        return TodayAttendanceStatusOut(date=dt.date.today().isoformat(), rows=[])

    now_default = dt.datetime.now(_tz(DEFAULT_TZ))
    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            all_events = repo.list_attendance_events(db, tenant_id)
            schedules = repo.all_schedules(db, tenant_id)
        finally:
            db.close()
    else:
        all_events = tracker.get_events()
        schedules = _schedule_store.all()

    rows = []

    for employee in _employee_records(eng, tenant_id):
        employee_id = employee["employee_id"]
        name = employee["name"]
        schedule = schedules.get(employee_id)
        if schedule is None:
            rows.append(
                {
                    "employee_id": employee_id,
                    "name": name,
                    "status": "no_schedule",
                    "has_schedule": False,
                }
            )
            continue

        tz_name = schedule.get("timezone") or DEFAULT_TZ
        tzinfo = _tz(tz_name)
        now = dt.datetime.now(tzinfo)
        today = now.date()
        day_key = DAYS[today.weekday()]
        shift = (schedule.get("days") or {}).get(day_key) or {}
        working = bool(shift.get("working"))
        shift_start = shift.get("start")
        shift_end = shift.get("end")

        today_events = _today_events_for_employee(all_events, employee_id, name, today, tzinfo)
        clock_in, clock_out = _first_shift_pair(today_events)
        clock_in_ts = float(clock_in.get("timestamp_ts")) if clock_in else None
        clock_out_ts = float(clock_out.get("timestamp_ts")) if clock_out else None

        if not working:
            status = "day_off"
            start_dt = end_dt = None
        else:
            start_dt = _local_time(today, str(shift_start or "09:00"), tzinfo)
            end_dt = _local_time(today, str(shift_end or "17:00"), tzinfo)
            if end_dt <= start_dt:
                end_dt += dt.timedelta(days=1)

            if clock_in_ts is None:
                status = "absent" if now >= start_dt else "on_time"
            elif clock_out_ts is not None:
                status = "complete"
            elif now >= end_dt:
                status = "missing_clockout"
            else:
                clock_in_dt = dt.datetime.fromtimestamp(clock_in_ts, tzinfo)
                status = "late" if clock_in_dt > start_dt else "on_time"

        end_for_hours = clock_out_ts or (now.timestamp() if clock_in_ts is not None else None)
        hours = None
        if clock_in_ts is not None and end_for_hours is not None:
            hours = round(max(0.0, (end_for_hours - clock_in_ts) / 3600.0), 2)

        minutes_late = 0
        if working and start_dt is not None:
            ref_ts = clock_in_ts if clock_in_ts is not None else now.timestamp()
            minutes_late = max(0, round((ref_ts - start_dt.timestamp()) / 60))

        rows.append(
            {
                "employee_id": employee_id,
                "name": name,
                "status": status,
                "shift_start": shift_start if working else None,
                "shift_end": shift_end if working else None,
                "timezone": tz_name,
                "clock_in_ts": clock_in_ts,
                "clock_out_ts": clock_out_ts,
                "clock_in_time": _format_ts(clock_in_ts, tzinfo),
                "clock_out_time": _format_ts(clock_out_ts, tzinfo),
                "hours": hours,
                "has_schedule": True,
                "day_off": not working,
                "alert": _status_alert(status, name, minutes_late, shift_start, shift_end),
            }
        )

    return TodayAttendanceStatusOut(
        date=now_default.date().isoformat(),
        timezone=DEFAULT_TZ,
        rows=rows,
    )


@app.get("/api/attendance/events")
def get_attendance_events(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    employee: Optional[str] = None,
    location_id: Optional[str] = None,
    tenant_id: Optional[uuid.UUID] = Depends(require_tenant),
):
    """Filterable attendance event log."""
    start_ts: Optional[float] = None
    end_ts: Optional[float] = None
    if start_date:
        try:
            start_ts = dt.datetime.strptime(start_date, "%Y-%m-%d").replace(
                tzinfo=dt.timezone.utc
            ).timestamp()
        except ValueError:
            pass
    if end_date:
        try:
            end_ts = (
                dt.datetime.strptime(end_date, "%Y-%m-%d").replace(
                    tzinfo=dt.timezone.utc
                )
                + dt.timedelta(days=1)
            ).timestamp()
        except ValueError:
            pass

    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            return repo.list_attendance_events(
                db,
                tenant_id,
                start_ts=start_ts,
                end_ts=end_ts,
                employee_name=employee,
                location_id=location_id,
            )
        finally:
            db.close()

    eng = require_engine()
    tracker = eng.get_attendance_tracker()
    if tracker is None:
        return []
    return tracker.get_events(
        start_ts=start_ts,
        end_ts=end_ts,
        employee_name=employee,
        location_id=location_id,
    )


@app.post("/api/attendance/notes")
def add_attendance_note(
    body: AttendanceNoteCreate,
    tenant_id: Optional[uuid.UUID] = Depends(require_tenant),
):
    """Add a manager note to an event (never modifies the original record)."""
    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            ok = repo.add_attendance_note(
                db, tenant_id, body.event_id, body.note, body.manager
            )
        finally:
            db.close()
        if not ok:
            raise HTTPException(status_code=404, detail="Event not found")
        return {"ok": True}

    eng = require_engine()
    tracker = eng.get_attendance_tracker()
    if tracker is None:
        raise HTTPException(status_code=503, detail="Attendance tracker not ready")
    ok = tracker.add_note(body.event_id, body.note, body.manager)
    if not ok:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"ok": True}


@app.get("/api/attendance/export/preview", response_model=ExportPreviewOut)
def preview_export(
    format: str = "gusto",
    start_date: str = "",
    end_date: str = "",
    location_id: Optional[str] = None,
    tenant_id: Optional[uuid.UUID] = Depends(require_tenant),
):
    eng = require_engine()
    tz_name = str(eng.settings.get("timezone", "UTC"))

    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            events = repo.list_attendance_events(db, tenant_id)
        finally:
            db.close()
        preview = compute_preview_from_events(
            events, format, start_date, end_date, location_id, tz_name=tz_name
        )
        return ExportPreviewOut(**preview)

    tracker = eng.get_attendance_tracker()
    if tracker is None:
        raise HTTPException(status_code=503, detail="Attendance tracker not ready")
    preview = compute_preview(tracker, format, start_date, end_date, location_id, tz_name=tz_name)
    return ExportPreviewOut(**preview)


@app.post("/api/attendance/export")
def export_attendance(
    body: ExportRequest,
    tenant_id: Optional[uuid.UUID] = Depends(require_tenant),
):
    """Generate a payroll CSV for download."""
    eng = require_engine()
    tz_name = str(eng.settings.get("timezone", "UTC"))

    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            events = repo.list_attendance_events(db, tenant_id)
        finally:
            db.close()
        csv_content = build_export_csv_from_events(
            events,
            body.format,
            body.start_date,
            body.end_date,
            body.location_id,
            tz_name=tz_name,
        )
        db = _open_db()
        try:
            repo.append_audit(
                db,
                tenant_id,
                "export",
                actor="manager",
                detail=f"{body.format} {body.start_date}–{body.end_date}",
            )
        finally:
            db.close()
    else:
        tracker = eng.get_attendance_tracker()
        if tracker is None:
            raise HTTPException(status_code=503, detail="Attendance tracker not ready")
        csv_content = build_export_csv(
            tracker,
            body.format,
            body.start_date,
            body.end_date,
            body.location_id,
            tz_name=tz_name,
        )
        audit = eng.get_audit_log()
        if audit:
            audit.log(
                "export",
                actor="manager",
                detail=f"{body.format} {body.start_date}–{body.end_date}",
            )

    # Fix #12: sanitize user-supplied fields before embedding in the HTTP header
    filename = (
        f"attendance_{_safe_filename_part(body.format)}"
        f"_{_safe_filename_part(body.start_date)}"
        f"_{_safe_filename_part(body.end_date)}.csv"
    )
    return StreamingResponse(
        io.BytesIO(csv_content.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Consent routes
# ---------------------------------------------------------------------------

@app.post("/api/consent")
async def record_consent(
    body: ConsentCreate,
    request: Request,
    tenant_id: Optional[uuid.UUID] = Depends(optional_tenant),
):
    eng = require_engine()
    ip = body.ip_address or (request.client.host if request.client else "unknown")

    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            repo.record_consent(
                db,
                tenant_id,
                employee_id=body.employee_id,
                employee_name=body.name,
                ip_address=ip,
                form_version=body.form_version,
            )
        finally:
            db.close()

    consent_mgr = eng.get_consent_manager()
    consent_mgr.record_consent(
        employee_id=body.employee_id,
        name=body.name,
        ip_address=ip,
        form_version=body.form_version,
    )
    return {"ok": True}


@app.get("/api/consent/{employee_id}", response_model=ConsentStatusOut)
def get_consent_status(
    employee_id: str,
    tenant_id: Optional[uuid.UUID] = Depends(optional_tenant),
):
    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            record = repo.get_consent(db, tenant_id, employee_id)
        finally:
            db.close()
        if record is None:
            return ConsentStatusOut(employee_id=employee_id, consented=False)
        return ConsentStatusOut(
            employee_id=employee_id,
            consented=record.get("consent_given", False),
            timestamp_utc=record.get("timestamp_utc"),
            form_version=record.get("form_version"),
        )

    eng = require_engine()
    consent_mgr = eng.get_consent_manager()
    record = consent_mgr.get_consent(employee_id)
    if record is None:
        return ConsentStatusOut(employee_id=employee_id, consented=False)
    return ConsentStatusOut(
        employee_id=employee_id,
        consented=record.get("consent_given", False),
        timestamp_utc=record.get("timestamp_utc"),
        form_version=record.get("form_version"),
    )


@app.post("/api/consent/{employee_id}/delete")
async def request_data_deletion(
    employee_id: str,
    request: Request,
    tenant_id: Optional[uuid.UUID] = Depends(require_tenant),
):
    eng = require_engine()

    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            repo.request_consent_deletion(db, tenant_id, employee_id)
            repo.append_audit(
                db,
                tenant_id,
                "deletion_request",
                actor=employee_id,
                detail="Employee requested biometric data deletion",
            )
        finally:
            db.close()

    consent_mgr = eng.get_consent_manager()
    consent_mgr.request_deletion(employee_id)
    audit = eng.get_audit_log()
    if audit:
        audit.log(
            "deletion_request",
            actor=employee_id,
            detail="Employee requested biometric data deletion",
        )

    return {"ok": True, "message": "Deletion request recorded. Account owner has been notified."}


@app.get("/api/audit")
def get_audit_log_api(
    limit: int = 50,
    tenant_id: Optional[uuid.UUID] = Depends(require_tenant),
):
    """Return the last N audit log entries."""
    # Fix #11: cap to prevent memory exhaustion on the file-based path
    limit = max(1, min(limit, 500))
    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            return repo.list_audit(db, tenant_id, limit=limit)
        finally:
            db.close()

    eng = vision_ref()
    if eng is None:
        return []
    audit = eng.get_audit_log()
    if audit is None:
        return []
    return audit.tail(limit)


@app.get("/api/settings")
def get_settings(tenant_id: Optional[uuid.UUID] = Depends(require_tenant)):
    base = load_settings()
    eng = vision_ref()
    if eng is not None:
        base = {**base, **eng.settings}

    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            tenant_settings = repo.get_settings_dict(db, tenant_id)
        finally:
            db.close()
        result = {**base, **tenant_settings}
    else:
        result = base

    # Fix #4: never expose the kiosk PIN over the API — verify it server-side
    result.pop("kiosk_pin", None)
    return result


@app.patch("/api/settings")
def patch_settings(
    body: SettingsPatch,
    tenant_id: Optional[uuid.UUID] = Depends(require_tenant),
):
    eng = require_engine()
    _extra_allowed = {
        "attendance_enabled", "attendance_min_confidence", "save_clock_in_snapshot",
        "location_id", "device_id", "data_retention_days", "timezone",
        "kiosk_pin", "consent_form_version",
        # UI / payroll preferences — stored in settings.json
        "company_name", "kiosk_clock_in_message",
        "default_export_format", "pay_period_start_day", "fail_streak_alert",
        # L1: kiosk_pin is returned in GET /api/settings so the frontend can compare it
        # client-side.  For stronger security, move PIN comparison to the server and
        # exclude kiosk_pin from the GET response.
    }
    allowed = set(DEFAULT_SETTINGS.keys()) | _extra_allowed
    updates = {k: v for k, v in body.settings.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid keys to update")

    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            repo.upsert_settings(db, tenant_id, updates)
            repo.append_audit(
                db,
                tenant_id,
                "settings_change",
                actor="manager",
                detail=str(list(updates.keys())),
            )
        finally:
            db.close()

    merged = {**eng.settings, **updates}
    path = default_settings_path()
    with open(path, "w") as f:
        json.dump(
            {k: merged[k] for k in merged if k not in ("memory_file", "log_file")},
            f,
            indent=2,
        )
    eng.settings = load_settings()
    if tenant_id is not None:
        from auty.db import repositories as repo

        db = _open_db()
        try:
            tenant_settings = repo.get_settings_dict(db, tenant_id)
            eng.settings = {**eng.settings, **tenant_settings}
        finally:
            db.close()
    import recognition as rec
    from vision import config as vcfg

    rec.configure(eng.settings)
    vcfg.configure(eng.settings)
    re = eng.response_engine
    re.greetings_enabled = bool(eng.settings.get("greetings_enabled", False))
    re.personality_enabled = bool(eng.settings.get("personality_enabled", False))
    re.greeting_bar_enabled = bool(eng.settings.get("greeting_bar_enabled", False))
    audit = eng.get_audit_log()
    if audit and tenant_id is None:
        audit.log("settings_change", actor="manager", detail=str(list(updates.keys())))
    return eng.settings


if _ASSETS.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_ASSETS)), name="frontend-assets")


@app.get("/")
async def root():
    if _ui_built():
        return Response(
            content=_index_bytes(),
            media_type="text/html",
            headers=_INDEX_HEADERS,
        )
    return HTMLResponse(_DEV_HINT)


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """React Router paths (e.g. /logs) — serve index.html when UI is built."""
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    if _ui_built():
        return Response(
            content=_index_bytes(),
            media_type="text/html",
            headers=_INDEX_HEADERS,
        )
    raise HTTPException(status_code=404, detail="UI not built")


# Shutdown is handled by FastAPI lifespan (eng.stop()). Do not run heavy cleanup
# inside a signal handler — it races uvicorn and can hang on "Waiting for shutdown".
