"""
Headless vision pipeline — extracted from main.py update_camera loop.
"""

from __future__ import annotations

import base64
import os
import queue
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

import cv2
import numpy as np

from utils.paths import ensure_directories, migrate_legacy_data
from presence_tracker import PresenceTracker, PresenceTransition, presence_to_api_dict
from attendance_tracker import AttendanceTracker
from audit_log import AuditLog
from consent_manager import ConsentManager

ensure_directories()
migrate_legacy_data()

import database as db_mod
import face_detection
import recognition as rec
from vision.enrollment.session import EnrollmentSession
from vision.insightface_app import models_ready
from vision.verify_detection import landmarks_valid, min_det_score
from vision.preprocess import preprocess_frame
from vision.quality import assess_face
import recognition_worker
import tracking as track_engine
import camera as camera_mod
import ui_overlay
from attention_manager import AttentionManager
from event_system import (
    AttentionShifted,
    EventBus,
    FaceDetected,
    FaceLost,
    FaceRecognized,
    StateChanged,
    UnknownFaceDetected,
)
from memory import Memory
from response_engine import ResponseEngine
from state_machine import AIState, FSMContext, StateMachine
from timing_controller import TimingController

from server.schemas import (
    AttendanceEventOut,
    EnrollmentPendingOut,
    EnrollmentProgressOut,
    FrameSnapshotOut,
    LogEntryOut,
    PresenceOut,
    TrackOut,
)
from server.settings_loader import load_settings

PROCESS_W, PROCESS_H = 960, 540
ENROLL_SAMPLE_COUNT = 12
ENROLL_FRAME_GAP = 3
ENROLL_COOLDOWN_SEC = 5
# Guided enrollment uses direct RetinaFace/Haar detection — not tracker IDs.
ENROLLMENT_DIRECT_TRACK_ID = 0


def _sanitize_name(name: str) -> str:
    safe = re.sub(r"[^\w\-]", "_", name.strip())
    return safe or "unknown"


def _blur_score(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var()


@dataclass
class _FrameSnapshot:
    frame_count: int
    fps: float
    jpeg: bytes
    payload: FrameSnapshotOut
    ws_payload: dict
    camera_ok: bool = True


class SessionLog:
    MAX = 200

    def __init__(self):
        self._entries: Deque[LogEntryOut] = deque(maxlen=self.MAX)
        self._lock = threading.Lock()

    def append(self, entry: LogEntryOut):
        with self._lock:
            self._entries.append(entry)

    def list_all(self) -> List[LogEntryOut]:
        with self._lock:
            return list(self._entries)

    def alerts(self) -> List[LogEntryOut]:
        with self._lock:
            return [
                e
                for e in self._entries
                if e.type in ("UNKNOWN", "ALERT", "ENROLLED")
            ]

    def clear(self):
        with self._lock:
            self._entries.clear()


class VisionEngine:
    def __init__(self):
        self.settings = load_settings()
        rec.configure(self.settings)
        from vision import config as vcfg

        vcfg.configure(self.settings)

        self.db = db_mod.FaceDatabase(self.settings)
        self.db.configure()
        if self.settings.get("reset_db_each_run", False):
            self.db.reset(clear_captures=True)
            print("[Auty] Cleared profiles and face database for this session.")
        else:
            self.db.load()
        from vision.matcher import sync_gallery

        sync_gallery(self.db.face_db, self.db.store)

        self.event_bus = EventBus()
        self.fsm = StateMachine(self.settings)
        self.attention_mgr = AttentionManager(self.settings)
        self.timing_controller = TimingController(self.settings)
        self.fsm.set_timing_controller(self.timing_controller)
        self.attention_mgr.set_timing_controller(self.timing_controller)
        self.memory = Memory(self.settings, self.db)
        self.response_engine = ResponseEngine(
            self.settings, self.event_bus, self.fsm, self.memory
        )
        self.rec_worker = recognition_worker.RecognitionWorker()
        self.hud_renderer = ui_overlay.HUDRenderer(
            self.settings, db_mod.CAPTURE_FOLDER
        )

        self._event_system_enabled = bool(
            self.settings.get("event_system_enabled", True)
        )
        self._async_recognition = bool(self.settings.get("async_recognition", True))

        self.camera_stream = camera_mod.CameraStream(
            self.settings, PROCESS_W, PROCESS_H
        )
        self._use_local_camera = self.camera_stream.enabled
        self.face_cascade = face_detection.create_haar_cascade()
        self.track_manager = track_engine.FaceTrackManager(
            self.settings,
            self.face_cascade,
            self._create_tracker,
            self._new_face_track,
        )
        self.response_engine.set_track_manager(self.track_manager)

        if self._event_system_enabled:
            self.event_bus.subscribe(StateChanged, self._on_state_changed)

        self.session_log = SessionLog()
        sessions_path = str(
            self.settings.get(
                "presence_sessions_path",
                self.settings.get("presence_sessions_file", "presence_sessions.json"),
            )
        )
        self.presence_tracker = PresenceTracker(
            self.settings,
            sessions_path=sessions_path,
            on_transition=self._on_presence_transition,
        )
        self.attendance_tracker = AttendanceTracker(
            log_path=str(self.settings.get("attendance_log_path", "data/attendance_log.jsonl")),
            notes_path=str(self.settings.get("attendance_notes_path", "data/attendance_notes.json")),
            location_id=str(self.settings.get("location_id", "main")),
            device_id=str(self.settings.get("device_id", "default")),
            min_confidence=float(
                self.settings.get("attendance_min_confidence", 0.75)
            ),
            provisional_prefix=str(
                self.settings.get("enrollment_provisional_prefix", "Guest")
            ),
            on_alert=self._on_attendance_alert,
        )
        self.audit_log = AuditLog(
            log_path=str(self.settings.get("audit_log_path", "data/audit_log.jsonl")),
        )
        self.consent_manager = ConsentManager(
            log_path=str(self.settings.get("consent_log_path", "data/consent_log.json")),
            form_version=str(self.settings.get("consent_form_version", "1.0")),
        )
        self._lock = threading.Lock()
        self._enroll_lock = threading.Lock()
        self._camera_frame_idx = 0
        self._latest: Optional[_FrameSnapshot] = None
        self._preview_jpeg: bytes = b""
        self._camera_stream_ok = False
        self._frame_queue: queue.Queue = queue.Queue(maxsize=1)
        self._started_at = time.time()
        self._fps_ema = 0.0

        self._frame_count = 0
        self._prev_track_ids: set = set()
        self._recognized_emitted: set = set()
        self._recognized_names_session: set = set()
        self._unknown_emitted: set = set()
        # Per-person kiosk action cooldown (name → timestamp of last CLOCK_IN/OUT).
        # Stored on the engine (not on tracks) so it survives track recycling and
        # async recognition worker callbacks.  30 s is enough to walk away from the
        # kiosk; the next visit after that fires a fresh action.
        self._kiosk_last_action: Dict[str, float] = {}
        self._KIOSK_COOLDOWN_SEC = 30.0
        # Track IDs that have already fired a kiosk clock action in the current
        # continuous visit.  Once a track fires CLOCK_IN or CLOCK_OUT we do NOT
        # fire again until the track disappears (person walks away) and a brand-new
        # track ID is assigned by ByteTrack.  This prevents the 30-second toggle
        # loop where someone standing in front of the camera bounces between
        # CLOCK_IN and CLOCK_OUT every 30 seconds.
        self._kiosk_acted_track_ids: set = set()

        self._enrollment = {
            "collecting": False,
            "samples": [],
            "pending": None,
            "pending_embeddings": [],
            "cooldown_until": 0.0,
            "manual_until": 0.0,
            "last_capture_ts": 0.0,
            "target_tid": None,
            "gap_counter": 0,
            "auto_committed": False,
            "provisional_name": None,
        }
        self.enrollment_session = EnrollmentSession()
        self._guided_enroll = bool(
            self.settings.get("guided_enrollment_enabled", True)
        )

        self._thread: Optional[threading.Thread] = None
        self._camera_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._stopped = False
        self._running = False
        self._camera_read_fail_streak = 0

        self.reset_session()

    def _create_tracker(self):
        kind = str(self.settings.get("tracker_type", "kcf")).lower()
        if kind == "csrt":
            if hasattr(cv2, "TrackerCSRT_create"):
                return cv2.TrackerCSRT_create()
            return cv2.legacy.TrackerCSRT_create()
        if hasattr(cv2, "TrackerKCF_create"):
            return cv2.TrackerKCF_create()
        return cv2.legacy.TrackerKCF_create()

    def _new_face_track(self, track_id: int) -> dict:
        hist = int(self.settings.get("embedding_history_size", 25))
        return {
            "id": track_id,
            "state": track_engine.TrackState.ACTIVE,
            "confirm_hits": 0,
            "confirm_miss": 0,
            "tracker": None,
            "bbox": (0, 0, 0, 0),
            "smooth_bbox": (0, 0, 0, 0),
            "missing_frames": 0,
            "last_seen": time.time(),
            "velocity": (0.0, 0.0),
            "predict_count": 0,
            "embedding_history": deque(maxlen=hist),
            "vote_history": deque(maxlen=hist),
            "locked_name": "UNKNOWN",
            "locked_score": None,
            "locked_since": 0.0,
            "pending_name": None,
            "pending_since": 0.0,
            "miss_count": 0,
            "fail_count": 0,
            "stable_count": 0,
            "last_learned_at": 0.0,
            "last_recognition_frame": -999,
            "last_recognition_time": 0.0,
            "last_embedding": None,
            "last_distance": None,
            "stability_pct": 0,
            "vote_ratio": 0.0,
            "lock_confirm_streak": 0,
            "lock_state": "unknown",
            "quality_score": 0.0,
            "blur_score": 0.0,
            "pose_yaw": 0.0,
            "kps": None,
            "lock_release_streak": 0,
            "last_match_score": -1.0,
            "last_match_margin": 0.0,
            "last_reject_reason": "",
            "last_best_name": "",
            "det_verified": False,
            # Kiosk: one action (CLOCK_IN or CLOCK_OUT) per track lifetime.
            # Cleared automatically when the track is destroyed and a new one
            # is created on the person's next approach.
            "kiosk_action_fired": False,
        }

    def _on_state_changed(self, event: StateChanged):
        if event.new_state == AIState.ALERT.value:
            self.session_log.append(
                LogEntryOut(
                    ts=time.time(),
                    type="ALERT",
                    detail=event.reason or event.new_state,
                )
            )

    def reset_session(self):
        if self.settings.get("reset_db_each_run", False):
            self.db.reset(clear_captures=True)
        if self.settings.get("reset_memory_each_run", True):
            self.memory.reset()

        self._frame_count = 0
        self._prev_track_ids = set()
        self._recognized_emitted = set()
        self._recognized_names_session = set()
        self._unknown_emitted = set()
        self.fsm.state = AIState.IDLE
        self.fsm.ctx = FSMContext()
        self.attention_mgr._current_primary = None
        self.timing_controller.reset()
        self.response_engine.sequences.cancel()
        self.track_manager.reset()
        self._enrollment = {
            "collecting": False,
            "samples": [],
            "pending": None,
            "pending_embeddings": [],
            "cooldown_until": 0.0,
            "manual_until": 0.0,
            "last_capture_ts": 0.0,
            "target_tid": None,
            "gap_counter": 0,
            "auto_committed": False,
            "provisional_name": None,
        }
        self._kiosk_last_action.clear()
        self._kiosk_acted_track_ids.clear()
        self.session_log.clear()
        self.presence_tracker.reset()

    def _on_presence_transition(self, transition: PresenceTransition):
        self.session_log.append(
            LogEntryOut(
                ts=transition.ts,
                type=transition.event,
                name=transition.name,
                detail=transition.detail,
            )
        )
        # Mirror presence transitions into the attendance tracker.
        if not self.settings.get("attendance_enabled", True):
            return
        # In kiosk mode, _try_fast_checkin is the sole driver of attendance records.
        # Presence auto-CHECK_OUT fires after presence_out_timeout_seconds (default 5 s)
        # of absence, which would call record_recognition and toggle the employee back
        # to CLOCKED_OUT — so every subsequent walk-up becomes a CLOCK_IN instead of
        # alternating correctly.  Block the mirror here; _try_fast_checkin handles
        # both CLOCK_IN and CLOCK_OUT directly.
        if self.settings.get("kiosk_fast_checkin", True):
            return
        name = transition.name
        profile = self.db.get_profile(name) or {}
        employee_id = str(profile.get("id") or name)
        conf = float(transition.confidence or 0.0)
        if conf <= 0.0:
            conf = float(
                self.settings.get(
                    "attendance_min_confidence",
                    self.settings.get("presence_min_lock_score", 0.75),
                )
            )
        if transition.event in ("CHECK_IN", "CHECK_OUT"):
            print(f"[attendance] {transition.event} name={name!r} conf={conf:.3f} employee_id={employee_id!r}")
            result = self.attendance_tracker.record_recognition(
                name=name,
                employee_id=employee_id,
                confidence=conf,
            )
            if result is None:
                print(f"[attendance] record_recognition returned None — confidence may be below threshold ({self.attendance_tracker._min_confidence})")

    def _on_attendance_alert(self, alert) -> None:
        self.session_log.append(
            LogEntryOut(
                ts=alert.ts,
                type="ALERT",
                detail=alert.detail,
            )
        )

    def get_attendance_tracker(self) -> AttendanceTracker:
        return self.attendance_tracker

    def get_audit_log(self) -> AuditLog:
        return self.audit_log

    def get_consent_manager(self) -> ConsentManager:
        return self.consent_manager

    def _build_presence_out(self) -> Optional[PresenceOut]:
        if not self.settings.get("presence_enabled", True):
            return None
        return PresenceOut(**presence_to_api_dict(self.presence_tracker.snapshot()))

    def get_presence(self) -> PresenceOut:
        out = self._build_presence_out()
        if out is None:
            return PresenceOut(**presence_to_api_dict(self.presence_tracker.snapshot()))
        return out

    def start(self):
        if self._running:
            return
        self._stop.clear()
        self._running = True
        self._camera_thread = None
        if self._use_local_camera:
            # Camera thread feeds the browser immediately, even while models load.
            self._camera_thread = threading.Thread(
                target=self._camera_loop, daemon=True, name="auty-camera"
            )
            self._camera_thread.start()
        if not models_ready():
            print("[Auty] Loading InsightFace (first run may download weights)…")
            rec.warmup_models()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="auty-vision"
        )
        self._thread.start()

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        self._stop.set()
        self._running = False
        # Release camera first so cap.read() unblocks on macOS AVFoundation.
        try:
            self.camera_stream.release()
        except Exception:
            pass
        if self._camera_thread and self._camera_thread.is_alive():
            self._camera_thread.join(timeout=2.0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.rec_worker.shutdown()
        try:
            self.memory.save(force=True)
            self.presence_tracker.flush(force=True)
        except Exception:
            pass
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass

    def get_snapshot(self) -> FrameSnapshotOut:
        with self._lock:
            if self._latest is None:
                return FrameSnapshotOut(
                    presence=self._build_presence_out(),
                )
            return self._latest.payload

    def _postgres_enabled(self) -> bool:
        return bool(os.environ.get("DATABASE_URL"))

    def _resolve_face_db(self) -> Dict[str, List]:
        """Recognition gallery: PostgreSQL per tenant when configured, else file store."""
        if not self._postgres_enabled():
            return self.db.face_db

        tenant_id = None
        try:
            from auty.db.context import get_current_tenant_context

            tenant_id = get_current_tenant_context()
        except ImportError:
            pass

        if tenant_id is None:
            try:
                from auty.auth import get_default_tenant_id

                tenant_id = get_default_tenant_id()
            except Exception:
                return self.db.face_db

        try:
            import uuid as _uuid

            from auty.db.connection import get_session_factory
            from auty.db.embedding_store import load_tenant_gallery

            db = get_session_factory()()
            try:
                gallery = load_tenant_gallery(db, _uuid.UUID(str(tenant_id)))
                if gallery:
                    return gallery
            finally:
                db.close()
        except Exception as exc:
            print(f"[Auty] PostgreSQL gallery load failed, using file store: {exc}")
        return self.db.face_db

    def persist_embeddings_to_postgres(self, tenant_id, name: str) -> None:
        """Write identity-store embeddings to PostgreSQL for this tenant."""
        if not self._postgres_enabled():
            return
        rec = self.db.store.find_by_name(name)
        if rec is None:
            return
        try:
            import uuid as _uuid

            employee_id = _uuid.UUID(str(rec.id))
            tenant_uuid = _uuid.UUID(str(tenant_id))
        except (ValueError, TypeError):
            return

        embs = [np.asarray(e, dtype=np.float32) for e in rec.embeddings if e is not None]
        if not embs:
            samples = self.db.face_db.get(name) or []
            embs = [np.asarray(e, dtype=np.float32) for e in samples]

        if not embs:
            return

        from auty.db.connection import get_session_factory
        from auty.db.embedding_store import save_embeddings

        db = get_session_factory()()
        try:
            save_embeddings(db, employee_id, tenant_uuid, embs)
        finally:
            db.close()

    def recognize_client_frame(
        self, jpeg_bytes: bytes, face_db: Optional[Dict[str, List]] = None
    ) -> FrameSnapshotOut:
        """Process a JPEG sent by the client device (e.g. iPad camera).

        Stateless relative to the server camera loop: runs detection +
        recognition + attendance in the calling thread without touching the
        track manager.  Returns a FrameSnapshotOut so the caller gets the
        same shape of data as the WebSocket broadcast.
        """
        import recognition as rec
        from vision.detector import detect as detect_faces
        from vision.matcher import match_identity

        # Decode JPEG → numpy BGR
        buf = np.frombuffer(jpeg_bytes, np.uint8)
        frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if frame is None or frame.size == 0:
            return self.get_snapshot()

        # Resize to pipeline resolution to match enrollment embeddings
        from vision.preprocess import preprocess_frame
        frame = preprocess_frame(frame)

        faces = detect_faces(frame, max_faces=1)
        if not faces:
            return self.get_snapshot()

        best = faces[0]
        x, y, w, h = best.bbox
        aligned = rec.align_face(frame, x, y, w, h, kps=best.kps)
        if aligned is None or aligned.size == 0:
            return self.get_snapshot()

        embedding = rec.extract_embedding(aligned)
        if embedding is None:
            return self.get_snapshot()

        min_score = float(self.settings.get(
            "presence_min_lock_score",
            self.settings.get("min_lock_score", 0.62),
        ))
        gallery = face_db if face_db is not None else self._resolve_face_db()
        name, score, _second, _dist = match_identity(gallery, embedding)
        if not name or name == "UNKNOWN" or score < min_score:
            return self.get_snapshot()

        # Reuse the kiosk clock in/out logic with a synthetic track
        now = time.time()
        if now - self._kiosk_last_action.get(name, 0.0) < self._KIOSK_COOLDOWN_SEC:
            return self.get_snapshot()

        profile = self.db.get_profile(name) or {}
        employee_id = str(profile.get("id") or name)
        if self._postgres_enabled():
            try:
                from auty.db.context import get_current_tenant_context
                from auty.db.connection import get_session_factory
                from auty.db import repositories as repo

                tid = get_current_tenant_context()
                if tid is None:
                    from auty.auth import get_default_tenant_id

                    tid = get_default_tenant_id()
                db = get_session_factory()()
                try:
                    row = repo.get_employee_by_name(db, tid, name)
                    if row is not None:
                        employee_id = str(row.id)
                finally:
                    db.close()
            except Exception:
                pass
        already_clocked_in = self.attendance_tracker.is_clocked_in(name)
        event = self.attendance_tracker.record_recognition(
            name=name, employee_id=employee_id, confidence=score
        )
        if event is not None:
            self._kiosk_last_action[name] = now
            presence_type = "CHECK_OUT" if already_clocked_in else "CHECK_IN"
            print(f"[client-cam] {name!r} → {'CLOCK_OUT' if already_clocked_in else 'CLOCK_IN'}")
            self.session_log.append(
                LogEntryOut(ts=event.timestamp_ts, type=presence_type, name=name)
            )
            if already_clocked_in:
                self.presence_tracker.force_check_out(name)
            else:
                self.presence_tracker.force_check_in(name, score)

        return self.get_snapshot()

    def get_jpeg(self) -> Optional[bytes]:
        """Live preview JPEG — updated by the camera thread, not the vision loop."""
        with self._lock:
            if self._preview_jpeg:
                return self._preview_jpeg
            if self._latest is None:
                return None
            return self._latest.jpeg or None

    def is_camera_ok(self) -> bool:
        with self._lock:
            if self._camera_stream_ok:
                return True
            if self._latest is not None:
                return bool(self._latest.camera_ok)
            return False

    def get_ws_broadcast(self) -> dict:
        """Pre-built payload for /api/ws — must stay fast (no model_dump per tick).

        Called via asyncio.to_thread so it runs in a worker thread, not on the
        uvloop event thread.  Lock acquisition and any CPU work here is safe.
        """
        with self._lock:
            cam_ok = self._camera_stream_ok or (
                bool(self._latest.camera_ok) if self._latest else False
            )
            if not cam_ok:
                return {"type": "error", "message": "Camera unavailable"}
            if self._latest is not None:
                return self._latest.ws_payload
        # Camera is up but the vision thread hasn't finished its first frame yet.
        # Return a lightweight status message so the frontend stays in loading state
        # rather than receiving a stale FrameSnapshotOut with frame_count=0 that
        # would cause LiveFeed to lock its lastCountRef at 0 and skip all future
        # frame_count=0 fallback redraws.
        return {"type": "status", "ready": True, "camera_ok": True}

    def get_health_light(self) -> dict:
        """Health for polling — avoids get_snapshot + repeated disk reads."""
        with self._lock:
            latest = self._latest
            frame_count = latest.frame_count if latest else 0
            fps = latest.fps if latest else 0.0
            cam_ok = self._camera_stream_ok or (
                bool(latest.camera_ok) if latest else False
            )
        return {
            "camera_ok": cam_ok,
            "db_loaded": bool(gallery := self._resolve_face_db()),
            "face_count": sum(len(v) for v in gallery.values()),
            "profile_count": len(self.db.load_profiles()),
            "fps": round(fps, 1),
            "uptime_seconds": round(time.time() - self._started_at, 1),
            "frame_count": frame_count,
        }

    def get_health(self) -> dict:
        h = self.get_health_light()
        return {
            "camera_ok": h["camera_ok"],
            "db_loaded": h["db_loaded"],
            "face_db_count": h["face_count"],
            "profile_count": h["profile_count"],
            "fps": h["fps"],
            "uptime_seconds": h["uptime_seconds"],
            "frame_count": h["frame_count"],
        }

    def _greet_stable(self) -> int:
        return int(self.settings.get("greet_stable_frames", 2))

    def _is_verified_human_face(self, track: dict) -> bool:
        """Strict gate: verified detection + landmarks + quality (blocks FP enroll/alert)."""
        if not bool(self.settings.get("track_require_verified_det", True)):
            return True
        if not track.get("det_verified", False):
            return False
        if track.get("missing_frames", 0) > 0:
            return False
        score = float(track.get("last_det_score", 0) or 0)
        if score < min_det_score():
            return False
        kps = track.get("kps")
        if kps is not None and not landmarks_valid(kps):
            return False
        if float(track.get("quality_score", 0) or 0) < float(
            self.settings.get("quality_min_recognize", 50)
        ):
            return False
        bbox = track.get("smooth_bbox") or track.get("bbox", (0, 0, 0, 0))
        area = float(bbox[2] * bbox[3])
        if area < float(self.settings.get("min_face_width", 50)) * float(
            self.settings.get("min_face_height", 50)
        ):
            return False
        return True

    def _can_enroll_tick(self, track: dict) -> bool:
        """Relaxed gate for guided enrollment capture (tick has its own quality checks)."""
        if track.get("missing_frames", 0) > 8:
            return False
        bbox = track.get("smooth_bbox") or track.get("bbox", (0, 0, 0, 0))
        min_w = float(self.settings.get("min_face_width", 50)) * 0.35
        min_h = float(self.settings.get("min_face_height", 50)) * 0.35
        if float(bbox[2]) < min_w or float(bbox[3]) < min_h:
            return False
        return True

    def _visible_tracks(self, tracks: Optional[List[dict]] = None) -> List[dict]:
        """Tracks safe to show in HUD / FSM / WebSocket (verified human only)."""
        src = tracks if tracks is not None else self.track_manager.active_tracks()
        return [t for t in src if self._is_verified_human_face(t)]

    def _track_is_known_stable(self, track: dict) -> bool:
        return (
            track.get("locked_name", "UNKNOWN") != "UNKNOWN"
            and track.get("stable_count", 0) >= self._greet_stable()
        )

    def _presence_observations(self, tracks: List[dict]) -> Dict[str, float]:
        if not self.settings.get("presence_enabled", True):
            return {}
        confirm_frames = int(self.settings.get("presence_confirm_frames", 8))
        use_confirm = bool(
            self.settings.get("presence_use_confirm_frames_for_filter", True)
        )
        min_score = float(
            self.settings.get(
                "presence_min_lock_score",
                self.settings.get("min_lock_score", 0.62),
            )
        )
        stable_need = confirm_frames if use_confirm else self._greet_stable()
        obs: Dict[str, float] = {}
        for track in tracks:
            if not self._is_verified_human_face(track):
                continue
            name = track.get("locked_name", "UNKNOWN")
            if name == "UNKNOWN":
                continue
            if track.get("stable_count", 0) < stable_need:
                continue
            if not use_confirm and not self._track_is_known_stable(track):
                continue
            score = float(track.get("locked_score", 0) or 0)
            if score < min_score:
                continue
            obs[name] = max(obs.get(name, 0.0), score)
        return obs

    def _track_is_unknown_stable(self, track: dict) -> bool:
        need = int(self.settings.get("unknown_min_stable_frames", 8))
        return (
            track.get("locked_name", "UNKNOWN") == "UNKNOWN"
            and track.get("stable_count", 0) >= need
            and self._is_verified_human_face(track)
        )

    def _bump_stability(self, track: dict, *, had_embedding: bool):
        if not had_embedding or not self._is_verified_human_face(track):
            if track.get("locked_name", "UNKNOWN") == "UNKNOWN":
                track["stable_count"] = 0
            return
        track["stable_count"] = min(track.get("stable_count", 0) + 1, 64)
        self._try_fast_checkin(track)

    def _try_fast_checkin(self, track: dict) -> None:
        """Simple kiosk logic:
          - Face seen, not clocked in  → CLOCK IN
          - Face seen, already clocked in → CLOCK OUT
        Exactly ONE action fires per visit (per unique track ID).  The person
        must walk away (track disappears) and return (new track ID assigned by
        ByteTrack) before the kiosk acts again.  This prevents the old 30-second
        toggle loop where someone standing continuously in frame alternated
        between CLOCK_IN and CLOCK_OUT every 30 seconds.
        """
        if not self.settings.get("kiosk_fast_checkin", True):
            return
        name = track.get("locked_name", "UNKNOWN")
        if name == "UNKNOWN":
            return
        # Skip provisional/guest identities — they are unconfirmed auto-enrollments
        # and should never generate payroll clock events.
        provisional_prefix = str(self.settings.get("enrollment_provisional_prefix", "Guest"))
        if name.startswith(provisional_prefix):
            return
        if track.get("stable_count", 0) < self._greet_stable():
            return
        score = float(track.get("locked_score") or 0.0)
        min_score = float(self.settings.get(
            "presence_min_lock_score",
            self.settings.get("min_lock_score", 0.62),
        ))
        if score < min_score:
            return

        # One action per track ID — once a track fires we skip it until the
        # person walks away and ByteTrack gives them a new ID on return.
        track_id = track.get("id")
        if track_id in self._kiosk_acted_track_ids:
            return

        # Determine and fire the action.
        profile = self.db.get_profile(name) or {}
        employee_id = str(profile.get("id") or name)
        already_clocked_in = self.attendance_tracker.is_clocked_in(name)

        event = self.attendance_tracker.record_recognition(
            name=name, employee_id=employee_id, confidence=score
        )
        if event is None:
            return  # below confidence threshold — don't mark track as acted

        # Mark this track as having already fired so we don't toggle again
        # while the person remains in frame.
        if track_id is not None:
            self._kiosk_acted_track_ids.add(track_id)
        # Keep the legacy time-based cooldown as a cross-session backstop.
        self._kiosk_last_action[name] = time.time()
        action_label = "CLOCK_OUT" if already_clocked_in else "CLOCK_IN"
        presence_type = "CHECK_OUT" if already_clocked_in else "CHECK_IN"
        print(f"[kiosk] {name!r} → {action_label}")
        self.session_log.append(
            LogEntryOut(ts=event.timestamp_ts, type=presence_type, name=name)
        )

        # Keep the presence dashboard in sync (no-op if within its own cooldown).
        if already_clocked_in:
            self.presence_tracker.force_check_out(name)
        else:
            self.presence_tracker.force_check_in(name, score)

    def _should_run_recognition(self, track: dict) -> bool:
        fc = self._frame_count
        locked = track.get("locked_name", "UNKNOWN")
        interval = int(self.settings["recognition_interval"])
        interval_locked = int(
            self.settings.get("recognition_interval_when_locked", 90)
        )
        locked_sec = float(self.settings.get("recognition_locked_seconds", 6.0))

        if locked == "UNKNOWN":
            return fc - track.get("last_recognition_frame", -999) >= interval
        if not self._track_is_known_stable(track):
            return fc - track.get("last_recognition_frame", -999) >= interval
        if time.time() - track.get("last_recognition_time", 0.0) < locked_sec:
            return False
        if fc - track.get("last_recognition_frame", -999) < interval_locked:
            return False
        return True

    def _queue_event(self, event):
        event.timestamp = time.time()
        event.frame_count = self._frame_count
        self.event_bus.emit(event)

    def _log_known(self, name: str, confidence: float, track_id: int):
        self.session_log.append(
            LogEntryOut(
                ts=time.time(),
                type="KNOWN",
                name=name,
                confidence=confidence,
                track_id=track_id,
            )
        )

    def _log_unknown(self, track_id: int):
        self.session_log.append(
            LogEntryOut(
                ts=time.time(),
                type="UNKNOWN",
                track_id=track_id,
                detail="Unrecognized face — no match in database",
            )
        )
        self.attendance_tracker.record_fail(track_id)

    def _emit_track_lifecycle(self, active_tids: set):
        for tid in active_tids - self._prev_track_ids:
            track = next(
                (t for t in self.track_manager.active_tracks() if t["id"] == tid),
                None,
            )
            bbox = (0, 0, 0, 0)
            if track:
                bbox = track.get("smooth_bbox") or track.get("bbox", bbox)
            self._queue_event(FaceDetected(track_id=tid, bbox=bbox))
        for tid in self._prev_track_ids - active_tids:
            self._queue_event(FaceLost(track_id=tid))
            self._recognized_emitted = {
                k for k in self._recognized_emitted if k[0] != tid
            }
            self._unknown_emitted.discard(tid)
            # Allow a fresh kiosk action when this person comes back (new track ID).
            self._kiosk_acted_track_ids.discard(tid)
        self._prev_track_ids = set(active_tids)

    def _sync_identity_events(self, tracks: List[dict]):
        for track in tracks:
            tid = track["id"]
            name = track.get("locked_name", "UNKNOWN")
            if name != "UNKNOWN" and self._track_is_known_stable(track):
                if name not in self._recognized_names_session:
                    conf = float(track.get("locked_score", 0) or 0)
                    self._queue_event(
                        FaceRecognized(track_id=tid, name=name, confidence=conf)
                    )
                    self._recognized_names_session.add(name)
                    self._recognized_emitted.add((tid, name))
                    self._log_known(name, conf, tid)
            elif (
                self._is_verified_human_face(track)
                and self._track_is_unknown_stable(track)
                and tid not in self._unknown_emitted
            ):
                best = float(track.get("last_match_score", -1.0))
                alert_max = float(self.settings.get("unknown_alert_max", 0.35))
                if best >= alert_max:
                    continue
                self._queue_event(
                    UnknownFaceDetected(
                        track_id=tid,
                        confidence=float(track.get("locked_score", 0) or 0),
                    )
                )
                self._unknown_emitted.add(tid)
                self._log_unknown(tid)

    def _process_frame_events(self):
        events = self.event_bus.drain()
        tracks = self.track_manager.active_tracks()
        primary_tid = self.attention_mgr.primary_track_id
        primary_name = "UNKNOWN"
        primary_stable = False
        if primary_tid is not None:
            pt = next((t for t in tracks if t["id"] == primary_tid), None)
            if pt:
                primary_name = pt.get("locked_name", "UNKNOWN")
                primary_stable = self._track_is_known_stable(pt)
        self.fsm.update_context(
            has_faces=bool(tracks),
            active_track_ids={t["id"] for t in tracks},
            primary_track_id=primary_tid,
            primary_name=primary_name,
            primary_stable=primary_stable,
        )
        transitions = self.fsm.process_events(events)
        events.extend(transitions)
        self.event_bus.dispatch(events)

    def _maybe_learn(self, name: str, embedding, score, track: dict):
        learn_th = float(self.settings.get("learn_threshold", 0.82))
        learn_streak = int(self.settings.get("learn_streak", 4))
        learn_iv = float(self.settings.get("learn_interval_seconds", 20))
        if name == "UNKNOWN" or score is None or score < learn_th:
            return
        if track.get("stable_count", 0) < learn_streak:
            return
        now = time.time()
        if now - track.get("last_learned_at", 0) < learn_iv:
            return
        if not self.db.embedding_is_new(name, embedding):
            return
        if self.db.add_embedding(name, embedding):
            self.db.save()
            track["last_learned_at"] = now

    def _apply_async(self, tid: int, embedding, tracks_by_id: dict):
        track = tracks_by_id.get(tid)
        if track is None:
            return
        had = embedding is not None
        gallery = self._resolve_face_db()
        if gallery:
            from vision.matcher import sync_gallery

            sync_gallery(gallery, self.db.store)
            rec.apply_embedding_to_track(gallery, track, embedding)
        self._bump_stability(track, had_embedding=had)
        if had and track.get("locked_name", "UNKNOWN") != "UNKNOWN":
            emb = track.get("last_embedding")
            if emb is not None:
                self._maybe_learn(
                    track["locked_name"], emb, track.get("locked_score"), track
                )

    def _process_enrollment(self, unknown_faces, active_tids: set):
        enr = self._enrollment
        if enr["pending"] is not None:
            return
        if enr["collecting"] and enr["target_tid"] not in active_tids:
            enr["collecting"] = False
            enr["samples"] = []
            enr["target_tid"] = None
            enr["gap_counter"] = 0
            return
        if time.time() < enr["cooldown_until"]:
            return
        if not unknown_faces:
            return

        area, tid, crop = max(unknown_faces, key=lambda item: item[0])
        if not enr["collecting"]:
            enr["collecting"] = True
            enr["target_tid"] = tid
            enr["samples"] = [crop.copy()]
            enr["gap_counter"] = 0
            return
        if tid != enr["target_tid"]:
            return
        enr["gap_counter"] += 1
        if enr["gap_counter"] >= ENROLL_FRAME_GAP:
            enr["gap_counter"] = 0
            enr["samples"].append(crop.copy())
            if len(enr["samples"]) >= ENROLL_SAMPLE_COUNT:
                enr["pending"] = max(enr["samples"], key=_blur_score).copy()
                enr["pending_embeddings"] = []
                for sample in enr["samples"]:
                    for emb in rec.extract_embeddings_robust(sample, max_samples=2):
                        enr["pending_embeddings"].append(emb)
                enr["collecting"] = False
                enr["samples"] = []
                enr["target_tid"] = None
                enr["gap_counter"] = 0

    def _build_tracks_out(self, tracks: List[dict]) -> List[TrackOut]:
        out = []
        for t in tracks:
            bbox = t.get("smooth_bbox") or t.get("bbox") or (0, 0, 0, 0)
            name = t.get("locked_name", "UNKNOWN")
            score = t.get("locked_score")
            conf = float(score) if score is not None else 0.0
            out.append(
                TrackOut(
                    id=int(t["id"]),
                    bbox=[int(v) for v in bbox],
                    name=name,
                    confidence=conf,
                    known=name != "UNKNOWN",
                    stability_pct=int(t.get("stability_pct", 0)),
                    quality_score=float(t.get("quality_score", 0)),
                    blur_score=float(t.get("blur_score", 0)),
                    vote_ratio=float(t.get("vote_ratio", 0)),
                    distance=float(t["last_distance"])
                    if t.get("last_distance") is not None
                    else None,
                    pose_yaw=float(t.get("pose_yaw", 0)),
                    lock_state=str(t.get("lock_state", "unknown")),
                    match_margin=float(t.get("last_match_margin", 0)),
                    reject_reason=str(t.get("last_reject_reason", "") or ""),
                    best_candidate=str(t.get("last_best_name", "") or ""),
                )
            )
        return out

    def _enrollment_out(self) -> EnrollmentPendingOut:
        enr = self._enrollment
        if enr["pending"] is None:
            return EnrollmentPendingOut(ready=False)
        ok, buf = cv2.imencode(
            ".jpg", enr["pending"], [int(cv2.IMWRITE_JPEG_QUALITY), 85]
        )
        b64 = base64.b64encode(buf).decode("ascii") if ok else None
        return EnrollmentPendingOut(
            ready=True,
            track_id=enr.get("target_tid"),
            image_b64=b64,
        )

    def enrollment_progress(self) -> EnrollmentProgressOut:
        with self._enroll_lock:
            p = self.enrollment_session.progress()
            # Always expose live sample count (session dict is source of truth).
            p["captured"] = len(self.enrollment_session.samples)
            min_auto = int(self.settings.get("enrollment_min_auto_save", 8))
            if self.enrollment_session.active:
                p["active"] = True
                p["ready_to_save"] = p["captured"] >= min_auto
                p["percent"] = min(
                    100.0, 100.0 * p["captured"] / max(1, min_auto)
                )
            p["auto_committed"] = bool(self._enrollment.get("auto_committed"))
            p["provisional_name"] = self._enrollment.get("provisional_name")
        if p.get("auto_committed"):
            p["ready_to_save"] = True
            p["captured"] = max(int(p.get("captured") or 0), min_auto)
            p["percent"] = 100.0
            if p.get("provisional_name"):
                p["instruction"] = (
                    f"Recognized as {p['provisional_name']} — add a name (optional)"
                )
            else:
                p["instruction"] = "Capture complete — enter a name to save"
        elif p.get("active") and not p.get("ready_to_save"):
            lr = p.get("last_reject_reason")
            if lr and (p.get("captured") or 0) < (p.get("min_auto") or 8):
                hints = {
                    "pose": "Face the camera directly",
                    "blur": "Hold still — image is blurry",
                    "quality": "Move closer or improve lighting",
                    "lighting": "Adjust lighting on your face",
                    "size": "Move closer to the camera",
                    "embed": "Hold still while we capture your face",
                }
                p["instruction"] = hints.get(lr, f"Adjust: {lr}")
        # After auto-commit the session is inactive so session.progress() returns
        # preview_b64=None.  Restore it from the last captured preview so the
        # frontend confirmation screen can show the employee's face.
        if p.get("auto_committed") and p.get("preview_b64") is None:
            last = self.enrollment_session.last_preview
            if last is None:
                # Fall back to the pending crop saved during provisional commit
                last = self._enrollment.get("pending")
            if last is not None:
                try:
                    ok, buf = cv2.imencode(
                        ".jpg", last, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
                    )
                    if ok:
                        p["preview_b64"] = base64.b64encode(buf).decode("ascii")
                except Exception:
                    pass
        return EnrollmentProgressOut(**p)

    def start_guided_enrollment(self, track_id: Optional[int] = None) -> bool:
        # An auto-commit is already pending — caller can go straight to save.
        if self._enrollment.get("auto_committed"):
            return True
        # Direct detection path — does not require ByteTrack/KCF tracks in frame.
        with self._enroll_lock:
            self.enrollment_session.start(ENROLLMENT_DIRECT_TRACK_ID)
            self._enrollment["collecting"] = False
            self._enrollment["manual_until"] = time.time() + 600
            self._enrollment["last_capture_ts"] = 0.0
        print("[Auty] Guided enrollment started (direct face detection)")
        return True

    def _guided_enrollment_capture_direct(self, frame: np.ndarray) -> None:
        """Capture samples via face detection on the live camera frame (tracker-independent)."""
        with self._enroll_lock:
            if not self.enrollment_session.active:
                return
            if self.enrollment_session.track_id != ENROLLMENT_DIRECT_TRACK_ID:
                self.enrollment_session.track_id = ENROLLMENT_DIRECT_TRACK_ID

            now = time.time()
            if now - float(self._enrollment.get("last_capture_ts", 0)) < 0.12:
                return

            try:
                detections = face_detection.detect_faces(
                    frame, self.face_cascade, self.settings
                )
            except Exception as exc:
                print(f"[Auty] Enrollment detect failed: {exc}")
                return

            if not detections:
                return

            det = max(
                detections,
                key=lambda d: float(d["bbox"][2]) * float(d["bbox"][3]),
            )
            bbox = det["bbox"]
            synth = {
                "id": ENROLLMENT_DIRECT_TRACK_ID,
                "bbox": bbox,
                "smooth_bbox": bbox,
                "kps": det.get("kps"),
                "pose_yaw": float(det.get("pose_yaw", 0)),
                "missing_frames": 0,
                "locked_name": "UNKNOWN",
            }
            accepted, reason = self.enrollment_session.tick(frame, synth)
            if accepted:
                n = len(self.enrollment_session.samples)
                min_a = int(self.settings.get("enrollment_min_auto_save", 8))
                self._enrollment["last_capture_ts"] = now
                print(f"[Auty] Enrollment sample {n}/{min_a}")
            elif reason and self.enrollment_session.tick_count % 20 == 0:
                print(f"[Auty] Enrollment: {reason}")

        if self.enrollment_session.active:
            self._maybe_commit_provisional()

    def cancel_guided_enrollment(self):
        self.enrollment_session.cancel()
        self._enrollment["auto_committed"] = False
        self._enrollment["provisional_name"] = None

    def commit_provisional_enrollment(self) -> Tuple[bool, str]:
        """Auto-save after minimum samples so recognition works without full 25-pose enroll."""
        if self._enrollment.get("auto_committed"):
            return True, str(self._enrollment.get("provisional_name") or "")

        min_auto = int(self.settings.get("enrollment_min_auto_save", 8))
        embeddings = self.enrollment_session.all_embeddings()
        if len(embeddings) < min_auto:
            return False, "Not enough samples"

        tid = self.enrollment_session.track_id
        prefix = str(self.settings.get("enrollment_provisional_prefix", "Guest"))
        # Use a timestamp-based suffix so provisional names never collide with
        # leftover identity-store records from a previous database reset.
        name = f"{prefix}-{int(time.time())}"

        crops = self.enrollment_session.all_crops()
        image_rel = None
        if crops:
            safe = _sanitize_name(name)
            # Unique suffix prevents a second enrollment from overwriting the
            # photo file of a different person who happened to get the same name.
            image_rel = os.path.join(db_mod.CAPTURE_FOLDER, f"{safe}_{int(time.time())}.jpg")
            cv2.imwrite(image_rel, crops[-1])

        profile = {
            "name": name,
            "age": "",
            "status": "FRIEND",
            "image": image_rel,
        }

        try:
            rec_meta = self.db.store.add_person(
                name,
                embeddings,
                image_path=image_rel,
                poses=self.enrollment_session.poses(),
                profile=profile,
            )
            profile["id"] = rec_meta.id
            self.db.save_profile(name, profile)
            self.db.face_db = self.db.store.build_face_db()
            self.db.save()
            from vision.matcher import sync_gallery

            sync_gallery(self.db.face_db, self.db.store)
        except Exception as exc:
            print(f"[Auty] Provisional enroll failed: {exc}")
            return False, str(exc)

        self._enrollment["auto_committed"] = True
        self._enrollment["provisional_name"] = name
        self._enrollment["target_tid"] = tid
        if self.enrollment_session.last_preview is not None:
            self._enrollment["pending"] = self.enrollment_session.last_preview.copy()

        self.enrollment_session.active = False
        self.enrollment_session.samples = []

        track = self.track_manager.get_track(tid) if tid is not None else None
        if track is not None:
            track["locked_name"] = name
            track["locked_score"] = 1.0
            track["lock_state"] = "locked"
            track["last_best_name"] = name
            track["stable_count"] = max(
                track.get("stable_count", 0),
                int(self.settings.get("greet_stable_frames", 2)),
            )
            self._recognized_names_session.add(name)
            self._recognized_emitted.add((tid, name))

        print(f"[Auty] Auto-enrolled {name} ({len(embeddings)} embedding(s))")
        self.session_log.append(
            LogEntryOut(ts=time.time(), type="ENROLLED", name=name)
        )
        self.audit_log.log("enrollment", actor="system", detail=f"Auto-enrolled {name}")
        return True, name

    def _maybe_commit_provisional(self) -> None:
        if not self._guided_enroll:
            return
        if self._enrollment.get("auto_committed"):
            return
        if not self.enrollment_session.active:
            return
        min_auto = int(self.settings.get("enrollment_min_auto_save", 8))
        if len(self.enrollment_session.samples) < min_auto:
            return
        self.commit_provisional_enrollment()

    def _track_area(self, track: dict) -> float:
        bbox = track.get("smooth_bbox") or track.get("bbox", (0, 0, 0, 0))
        return float(bbox[2] * bbox[3])

    def _tracks_for_enrollment(self) -> List[dict]:
        """Live tracker faces only — never snapshot IDs (they don't match vision loop)."""
        max_miss = int(self.settings.get("max_missing_frames", 15))
        candidates: List[dict] = []
        for t in self.track_manager.tracks.values():
            if t.get("state") == track_engine.TrackState.REMOVED:
                continue
            if t.get("missing_frames", 0) > max_miss:
                continue
            bbox = t.get("smooth_bbox") or t.get("bbox")
            if not bbox or float(bbox[2]) * float(bbox[3]) < 100:
                continue
            candidates.append(t)
        return candidates

    def _enrollment_track_for_frame(
        self, tracks_by_id: Dict[int, dict]
    ) -> Optional[dict]:
        """Resolve which track to sample — follows face if the locked id drifts."""
        if not self.enrollment_session.active:
            return None
        etid = self.enrollment_session.track_id
        track = tracks_by_id.get(etid) if etid is not None else None
        if track is not None and track.get("missing_frames", 0) <= 5:
            if self._can_enroll_tick(track):
                return track
        candidates = [
            t for t in tracks_by_id.values() if self._can_enroll_tick(t)
        ]
        if not candidates:
            return None
        best = max(candidates, key=self._track_area)
        self.enrollment_session.track_id = best["id"]
        return best

    def _maybe_auto_start_enrollment(self, tracks: List[dict]) -> None:
        """Start guided capture when an unknown face is stable — no button press."""
        if not self._guided_enroll:
            return
        if not bool(self.settings.get("auto_enrollment_enabled", True)):
            return
        if self.enrollment_session.active:
            return
        if self._enrollment.get("auto_committed"):
            return
        if self._enrollment.get("pending") is not None:
            return
        if time.time() < self._enrollment.get("cooldown_until", 0.0):
            return
        if time.time() < self._enrollment.get("manual_until", 0.0):
            return

        enroll_stable = int(self.settings.get("enrollment_min_stable_frames", 10))
        candidates = [
            t
            for t in tracks
            if t.get("locked_name", "UNKNOWN") == "UNKNOWN"
            and t.get("stable_count", 0) >= enroll_stable
            and self._is_verified_human_face(t)
        ]
        if not candidates:
            return

        track = max(candidates, key=self._track_area)
        self.enrollment_session.start(track["id"])
        self._enrollment["collecting"] = False
        print(f"[Auty] Auto-started enrollment on track T{track['id']}")

    def _camera_loop(self):
        """Dedicated capture loop — keeps /api/frame.jpg live while vision runs slowly on CPU."""
        while not self._stop.is_set():
            ret, frame = self.camera_stream.read()
            if ret and frame is not None:
                ok, buf = cv2.imencode(
                    ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75]
                )
                if ok:
                    with self._lock:
                        self._preview_jpeg = buf.tobytes()
                        self._camera_stream_ok = True
                self._camera_read_fail_streak = 0
                frame_copy = frame.copy()
                self._camera_frame_idx += 1
                if (
                    self._guided_enroll
                    and self.enrollment_session.active
                    and self.enrollment_session.track_id == ENROLLMENT_DIRECT_TRACK_ID
                    and self._camera_frame_idx % 4 == 0
                ):
                    self._guided_enrollment_capture_direct(frame_copy)
                try:
                    self._frame_queue.put_nowait(frame_copy)
                except queue.Full:
                    try:
                        self._frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._frame_queue.put_nowait(frame_copy)
                    except queue.Full:
                        pass
            else:
                self._camera_read_fail_streak += 1
                if self._camera_read_fail_streak >= 8:
                    with self._lock:
                        self._camera_stream_ok = False
            if self._stop.wait(0.033):
                break

    def _process_frame_data(self, frame: np.ndarray) -> bool:
        frame = preprocess_frame(frame)
        self.track_manager.step(frame, self._frame_count)
        active_tids: set = set()
        unknown_faces = []
        profiles = self.db.load_profiles()
        tracks_by_id = {
            t["id"]: t
            for t in self.track_manager.tracks.values()
            if t.get("state") != track_engine.TrackState.REMOVED
        }

        for tid, embedding in self.rec_worker.poll():
            self._apply_async(tid, embedding, tracks_by_id)

        for track in self.track_manager.active_tracks():
            tid = track["id"]
            active_tids.add(tid)
            x, y, w, h = track.get("smooth_bbox") or track.get("bbox", (0, 0, 0, 0))

            fq = assess_face(
                frame, (x, y, w, h), pose_yaw=float(track.get("pose_yaw", 0))
            )
            track["quality_score"] = fq.quality_score
            track["blur_score"] = fq.blur_score

            if track.get("locked_name", "UNKNOWN") == "UNKNOWN" and not fq.passed:
                track["stable_count"] = 0

            gallery = self._resolve_face_db()
            need_rec = (
                bool(gallery)
                and self._should_run_recognition(track)
                and fq.passed
            )
            enrolling_tid = self.enrollment_session.track_id
            need_enroll_align = (
                self._guided_enroll
                and enrolling_tid is not None
                and tid == enrolling_tid
                and fq.passed
            ) or (
                not self._guided_enroll
                and track.get("locked_name", "UNKNOWN") == "UNKNOWN"
                and fq.passed
            )
            aligned = None
            if need_rec or need_enroll_align:
                aligned = rec.align_face(frame, x, y, w, h, kps=track.get("kps"))
            elif self._track_is_known_stable(track):
                track["miss_count"] = 0

            if need_rec and aligned is not None and aligned.size != 0:
                if self._async_recognition:
                    if self.rec_worker.submit(tid, aligned):
                        track["last_recognition_frame"] = self._frame_count
                        track["last_recognition_time"] = time.time()
                else:
                    track["last_recognition_frame"] = self._frame_count
                    track["last_recognition_time"] = time.time()
                    rec.recognize_track(gallery, track, aligned)
                    self._bump_stability(
                        track, had_embedding=track.get("last_embedding") is not None
                    )
                    if track.get("locked_name", "UNKNOWN") != "UNKNOWN":
                        emb = track.get("last_embedding")
                        if emb is not None:
                            self._maybe_learn(
                                track["locked_name"],
                                emb,
                                track.get("locked_score"),
                                track,
                            )

            if (
                track.get("locked_name", "UNKNOWN") == "UNKNOWN"
                and aligned is not None
                and aligned.size != 0
            ):
                unknown_faces.append((w * h, tid, aligned.copy()))

        tracks = self.track_manager.active_tracks()
        visible = self._visible_tracks(tracks)

        if self.enrollment_session.active:
            if self.enrollment_session.track_id != ENROLLMENT_DIRECT_TRACK_ID:
                tick_track = self._enrollment_track_for_frame(tracks_by_id)
                if tick_track is not None:
                    with self._enroll_lock:
                        accepted, _ = self.enrollment_session.tick(frame, tick_track)
                        if accepted:
                            n = len(self.enrollment_session.samples)
                            print(f"[Auty] Enrollment sample {n}")
                    self._maybe_commit_provisional()
        self._maybe_auto_start_enrollment(visible)
        visible_ids = {t["id"] for t in visible}
        self._emit_track_lifecycle(visible_ids)

        prev_primary = self.attention_mgr.primary_track_id
        attn = self.attention_mgr.select(visible, (PROCESS_W, PROCESS_H))
        primary_track = attn.primary_track
        primary_name = (
            primary_track.get("locked_name", "UNKNOWN") if primary_track else "UNKNOWN"
        )
        self.timing_controller.update(visible, attn.primary_track_id, primary_name)
        familiar = self.timing_controller.is_familiar_session(primary_name)

        self.response_engine.set_frame_context(
            visible,
            profiles,
            self._frame_count,
            primary_track_id=attn.primary_track_id,
            secondary_track_ids=attn.secondary_track_ids,
            familiar=familiar,
        )
        self._sync_identity_events(visible)

        if self.settings.get("presence_enabled", True):
            self.presence_tracker.update(self._presence_observations(visible))

        if attn.primary_track_id != prev_primary:
            self._queue_event(
                AttentionShifted(
                    previous_track_id=prev_primary,
                    track_id=attn.primary_track_id,
                )
            )

        if self._event_system_enabled:
            self._process_frame_events()

        frame, ctx = self.response_engine.process_frame(frame, primary_track)
        self.memory.save()
        self.presence_tracker.flush()

        if self.settings.get("hud_enabled", True):
            frame = self.hud_renderer.draw_all(
                frame,
                visible,
                profiles,
                self._frame_count,
                brain_ctx=ctx,
                primary_track_id=attn.primary_track_id,
            )

        if self._guided_enroll:
            prog = self.enrollment_session.progress()
            if prog.get("ready_to_save") and self.enrollment_session.last_preview is not None:
                self._enrollment["pending"] = self.enrollment_session.last_preview.copy()
        elif not self.enrollment_session.active:
            self._process_enrollment(unknown_faces, active_tids)
        self._frame_count += 1

        mood = ctx.mood.value if hasattr(ctx.mood, "value") else str(ctx.mood)
        payload = FrameSnapshotOut(
            frame_count=self._frame_count,
            fps=round(self._fps_ema, 1),
            fsm_state=str(ctx.state),
            mood=mood,
            status_line=str(ctx.status_line or ctx.state),
            primary_track_id=attn.primary_track_id,
            tracks=self._build_tracks_out(visible),
            log_tail=self.session_log.list_all()[-20:],
            enrollment=self._enrollment_out(),
            enrollment_progress=self.enrollment_progress(),
            presence=self._build_presence_out(),
            recent_attendance=[
                AttendanceEventOut(**ev.to_dict())
                for ev in self.attendance_tracker.get_recent_events(5)
            ],
            frame_width=PROCESS_W,
            frame_height=PROCESS_H,
        )

        ok, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        jpeg_bytes = jpeg.tobytes() if ok else b""
        ws_payload = payload.model_dump()

        with self._lock:
            preview = self._preview_jpeg
            self._latest = _FrameSnapshot(
                frame_count=self._frame_count,
                fps=self._fps_ema,
                jpeg=jpeg_bytes if jpeg_bytes else preview,
                payload=payload,
                ws_payload=ws_payload,
                camera_ok=True,
            )
        return True

    def _loop(self):
        while not self._stop.is_set():
            try:
                frame = self._frame_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            t0 = time.perf_counter()
            try:
                self._process_frame_data(frame)
            except Exception as exc:
                print(f"[Auty] Vision frame error: {exc}")
                continue
            elapsed = time.perf_counter() - t0
            if elapsed > 0:
                inst_fps = 1.0 / elapsed
                self._fps_ema = inst_fps if self._fps_ema <= 0 else (
                    0.85 * self._fps_ema + 0.15 * inst_fps
                )

    def _refresh_tracks_after_enroll(self, name: str):
        """Force active tracks to re-run recognition against the new embeddings."""
        key = name.strip().lower()
        self._recognized_names_session = {
            n for n in self._recognized_names_session if n.strip().lower() != key
        }
        self._recognized_emitted = {
            pair
            for pair in self._recognized_emitted
            if pair[1].strip().lower() != key
        }
        for track in self.track_manager.active_tracks():
            track["last_recognition_frame"] = -999
            track["stable_count"] = 0
            track["pending_name"] = None
            track["pending_since"] = 0.0
            track["miss_count"] = 0
            if track.get("locked_name", "UNKNOWN").strip().lower() == key:
                track["locked_name"] = "UNKNOWN"
                track["locked_score"] = None

    def skip_enrollment(self):
        enr = self._enrollment
        enr["pending"] = None
        enr["cooldown_until"] = time.time() + ENROLL_COOLDOWN_SEC
        enr["collecting"] = False
        enr["samples"] = []
        enr["target_tid"] = None
        enr["gap_counter"] = 0
        enr["auto_committed"] = False
        enr["provisional_name"] = None
        self.enrollment_session.cancel()

    def save_profile(
        self,
        name: str,
        age: str,
        status: str,
        *,
        image_b64: Optional[str] = None,
        extra_images: Optional[List[str]] = None,
        allow_low_confidence: bool = False,
    ) -> Tuple[bool, str]:
        enr = self._enrollment
        name = name.strip()
        if not name:
            return False, "Name is required"

        provisional = enr.get("provisional_name")
        if (
            provisional
            and enr.get("auto_committed")
            and name.strip().lower() == str(provisional).strip().lower()
        ):
            prof = self.db.get_profile(name) or {
                "name": name,
                "age": age,
                "status": status or "FRIEND",
            }
            prof["age"] = age
            prof["status"] = status or "FRIEND"
            self.db.save_profile(name, prof)
            enr["pending"] = None
            enr["cooldown_until"] = time.time() + ENROLL_COOLDOWN_SEC
            enr["auto_committed"] = False
            enr["provisional_name"] = None
            self.enrollment_session.cancel()
            return True, name

        if provisional and name.strip().lower() != str(provisional).strip().lower():
            if not self.db.rename_profile(provisional, name):
                return False, f"Could not rename {provisional} to {name}"
            from vision.matcher import sync_gallery

            sync_gallery(self.db.face_db, self.db.store)
            enr["provisional_name"] = name
            self._refresh_tracks_after_enroll(name)
            track = self.track_manager.get_track(enr.get("target_tid"))
            if track is not None:
                track["locked_name"] = name
            self.enrollment_session.cancel()
            enr["pending"] = None
            enr["cooldown_until"] = time.time() + ENROLL_COOLDOWN_SEC
            enr["auto_committed"] = False
            self.session_log.append(
                LogEntryOut(ts=time.time(), type="ENROLLED", name=name)
            )
            return True, name

        guided_embeddings = []
        if self.enrollment_session.active or self.enrollment_session.samples:
            guided_embeddings = self.enrollment_session.all_embeddings()
            crops = self.enrollment_session.all_crops()
            if crops:
                pending_bgr = crops[-1]
            else:
                pending_bgr = enr.get("pending")
        else:
            pending_bgr = enr.get("pending")

        if image_b64:
            try:
                payload = image_b64.strip()
                if "," in payload and payload.startswith("data:"):
                    payload = payload.split(",", 1)[1]
                raw = base64.b64decode(payload)
                arr = np.frombuffer(raw, dtype=np.uint8)
                decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if decoded is not None and decoded.size > 0:
                    pending_bgr = decoded
            except Exception:
                pass

        if pending_bgr is None or pending_bgr.size == 0:
            return False, "No face ready to enroll — wait for the snapshot, then save"

        safe = _sanitize_name(name)
        image_rel = os.path.join(db_mod.CAPTURE_FOLDER, f"{safe}_{int(time.time())}.jpg")
        cv2.imwrite(image_rel, pending_bgr)

        profile = {
            "name": name,
            "age": age,
            "status": status or "FRIEND",
            "image": image_rel,
        }

        try:
            embeddings = list(guided_embeddings or enr.get("pending_embeddings", []))
            if not embeddings:
                embeddings = rec.extract_embeddings_robust(pending_bgr)
            if not embeddings:
                return (
                    False,
                    "Could not generate embedding — check lighting and face the camera",
                )

            existing = self.db.store.find_by_name(name)
            if existing:
                for emb in embeddings:
                    self.db.add_embedding(name, emb)
                rec_meta = existing
            else:
                rec_meta = self.db.store.add_person(
                    name,
                    embeddings,
                    image_path=image_rel,
                    poses=self.enrollment_session.poses()
                    if self.enrollment_session.samples
                    else [],
                    profile=profile,
                )
            profile["id"] = rec_meta.id
            self.db.save_profile(name, profile)

            # Process additional images (device-camera 3-photo flow).
            if extra_images:
                for img_b64_extra in extra_images:
                    try:
                        ep = img_b64_extra.strip()
                        if "," in ep and ep.startswith("data:"):
                            ep = ep.split(",", 1)[1]
                        raw_e = base64.b64decode(ep)
                        arr_e = np.frombuffer(raw_e, dtype=np.uint8)
                        decoded_e = cv2.imdecode(arr_e, cv2.IMREAD_COLOR)
                        if decoded_e is not None and decoded_e.size > 0:
                            extra_embs = rec.extract_embeddings_robust(decoded_e)
                            for emb in extra_embs:
                                self.db.add_embedding(name, emb)
                    except Exception:
                        pass  # Best-effort; don't fail enrolment for extra images

            self.db.face_db = self.db.store.build_face_db()
            self.db.save()
            from vision.matcher import sync_gallery

            sync_gallery(self.db.face_db, self.db.store)
            self.response_engine.on_profile_saved(name)
            gallery = self._resolve_face_db()
            n_samples = len(gallery.get(name, []))
            if n_samples == 0:
                return (
                    False,
                    "Could not generate embedding — check lighting and face the camera",
                )
            if extra_images and n_samples < 3 and not allow_low_confidence:
                confidence = round(min(n_samples / 3.0, 1.0), 2)
                return (
                    False,
                    f"LOW_CONFIDENCE:{confidence}",
                )
            print(f"[Auty] Enrolled {name} ({n_samples} embedding(s) in database)")
            try:
                from auty.db.context import get_current_tenant_context

                tid = get_current_tenant_context()
                if tid is not None:
                    self.persist_embeddings_to_postgres(tid, name)
            except Exception as persist_exc:
                print(f"[Auty] PostgreSQL embedding persist: {persist_exc}")
        except Exception as exc:
            print(f"[Auty] Enrollment error: {exc}")
            import traceback

            traceback.print_exc()
            return False, f"Enrollment failed: {exc}"

        self._refresh_tracks_after_enroll(name)
        enr["pending"] = None
        enr["pending_embeddings"] = []
        enr["cooldown_until"] = time.time() + ENROLL_COOLDOWN_SEC
        enr["collecting"] = False
        enr["samples"] = []
        enr["auto_committed"] = False
        enr["provisional_name"] = None
        self.enrollment_session.cancel()

        self.session_log.append(
            LogEntryOut(ts=time.time(), type="ENROLLED", name=name)
        )
        self.audit_log.log("enrollment", actor="manager", detail=f"Enrolled {name}")
        return True, name


_engine: Optional[VisionEngine] = None
_engine_lock = threading.Lock()


def get_engine() -> VisionEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = VisionEngine()
            _engine.start()
        return _engine
