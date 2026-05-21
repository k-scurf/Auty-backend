"""
Headless vision pipeline — extracted from main.py update_camera loop.
"""

from __future__ import annotations

import base64
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

import cv2
import numpy as np

from utils.paths import ensure_directories, migrate_legacy_data

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
import user_emotion
from attention_manager import AttentionManager
from event_system import (
    AttentionShifted,
    EmotionUpdated,
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
    EnrollmentPendingOut,
    EnrollmentProgressOut,
    FrameSnapshotOut,
    LogEntryOut,
    TrackOut,
)
from server.settings_loader import load_settings

PROCESS_W, PROCESS_H = 960, 540
ENROLL_SAMPLE_COUNT = 12
ENROLL_FRAME_GAP = 3
ENROLL_COOLDOWN_SEC = 5


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
        self.emotion_analyzer = user_emotion.UserEmotionAnalyzer(self.settings)
        self.rec_worker = recognition_worker.RecognitionWorker()
        self.hud_renderer = ui_overlay.HUDRenderer(
            self.settings, db_mod.CAPTURE_FOLDER
        )

        self._emotion_enabled = bool(self.settings.get("user_emotion_enabled", False))
        self._event_system_enabled = bool(
            self.settings.get("event_system_enabled", True)
        )
        self._async_recognition = bool(self.settings.get("async_recognition", True))

        self.camera_stream = camera_mod.CameraStream(
            self.settings, PROCESS_W, PROCESS_H
        )
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
        self._lock = threading.Lock()
        self._latest: Optional[_FrameSnapshot] = None
        self._started_at = time.time()
        self._fps_ema = 0.0

        self._frame_count = 0
        self._prev_track_ids: set = set()
        self._recognized_emitted: set = set()
        self._recognized_names_session: set = set()
        self._unknown_emitted: set = set()
        self._last_emotion_by_tid: dict = {}

        self._enrollment = {
            "collecting": False,
            "samples": [],
            "pending": None,
            "pending_embeddings": [],
            "cooldown_until": 0.0,
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
        self._stop = threading.Event()
        self._running = False

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
            "last_recognition_frame": -1,
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
        self._last_emotion_by_tid = {}
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
            "target_tid": None,
            "gap_counter": 0,
            "auto_committed": False,
            "provisional_name": None,
        }
        self.session_log.clear()

    def start(self):
        if self._running:
            return
        if not models_ready():
            print("[Auty] Loading InsightFace (first run may download weights)…")
            rec.warmup_models()
        self._stop.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="auty-vision"
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self.rec_worker.shutdown()
        self.memory.save(force=True)
        self.camera_stream.release()
        cv2.destroyAllWindows()

    def get_snapshot(self) -> FrameSnapshotOut:
        with self._lock:
            if self._latest is None:
                return FrameSnapshotOut()
            return self._latest.payload

    def get_jpeg(self) -> Optional[bytes]:
        with self._lock:
            if self._latest is None:
                return None
            return self._latest.jpeg

    def get_health(self) -> dict:
        snap = self.get_snapshot()
        with self._lock:
            cam_ok = self._latest.camera_ok if self._latest else False
        return {
            "camera_ok": cam_ok,
            "db_loaded": bool(self.db.face_db),
            "face_db_count": len(self.db.face_db),
            "profile_count": len(self.db.load_profiles()),
            "fps": round(snap.fps, 1),
            "uptime_seconds": round(time.time() - self._started_at, 1),
            "frame_count": snap.frame_count,
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

    def _visible_tracks(self, tracks: Optional[List[dict]] = None) -> List[dict]:
        """Tracks safe to show in HUD / FSM / WebSocket (verified human only)."""
        src = tracks if tracks is not None else self.track_manager.active_tracks()
        return [t for t in src if self._is_verified_human_face(t)]

    def _track_is_known_stable(self, track: dict) -> bool:
        return (
            track.get("locked_name", "UNKNOWN") != "UNKNOWN"
            and track.get("stable_count", 0) >= self._greet_stable()
        )

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

    def _should_run_emotion(self, track: dict) -> bool:
        if not self._emotion_enabled or not self.emotion_analyzer.enabled:
            return False
        interval = self.emotion_analyzer.interval_for_track(track)
        return self._frame_count - track.get("last_emotion_frame", -999) >= interval

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
                detail="No match in database",
            )
        )

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
            self._last_emotion_by_tid.pop(tid, None)
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
        if self.db.face_db:
            from vision.matcher import sync_gallery

            sync_gallery(self.db.face_db, self.db.store)
            rec.apply_embedding_to_track(self.db.face_db, track, embedding)
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
            emo = t.get("user_emotion")
            out.append(
                TrackOut(
                    id=int(t["id"]),
                    bbox=[int(v) for v in bbox],
                    name=name,
                    confidence=conf,
                    known=name != "UNKNOWN",
                    stability_pct=int(t.get("stability_pct", 0)),
                    user_emotion=str(emo) if emo else None,
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
        p = self.enrollment_session.progress()
        p["auto_committed"] = bool(self._enrollment.get("auto_committed"))
        p["provisional_name"] = self._enrollment.get("provisional_name")
        if p["auto_committed"] and p.get("provisional_name"):
            p["ready_to_save"] = True
            p["instruction"] = (
                f"Recognized as {p['provisional_name']} — add a name (optional)"
            )
        return EnrollmentProgressOut(**p)

    def start_guided_enrollment(self, track_id: Optional[int] = None) -> bool:
        tracks = self.track_manager.active_tracks()
        if not tracks:
            return False
        if track_id is None:
            track = max(
                tracks,
                key=lambda t: (t.get("smooth_bbox") or t.get("bbox", (0, 0, 0, 0)))[2]
                * (t.get("smooth_bbox") or t.get("bbox", (0, 0, 0, 0)))[3],
            )
            track_id = track["id"]
        self.enrollment_session.start(track_id)
        self._enrollment["collecting"] = False
        return True

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
        name = f"{prefix}-{tid}"

        crops = self.enrollment_session.all_crops()
        image_rel = None
        if crops:
            safe = _sanitize_name(name)
            image_rel = os.path.join(db_mod.CAPTURE_FOLDER, f"{safe}.jpg")
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

    def _process_one_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        ret, frame = self.camera_stream.read()
        if not ret:
            return False, None

        frame = preprocess_frame(frame)
        self.track_manager.step(frame, self._frame_count)
        active_tids: set = set()
        unknown_faces = []
        profiles = self.db.load_profiles()
        tracks_by_id = {t["id"]: t for t in self.track_manager.active_tracks()}

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

            if (
                self.enrollment_session.active
                and tid == self.enrollment_session.track_id
                and self._is_verified_human_face(track)
            ):
                self.enrollment_session.tick(frame, track)

            need_rec = (
                bool(self.db.face_db)
                and self._should_run_recognition(track)
                and fq.passed
            )
            need_emo = self._should_run_emotion(track)
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
            if need_rec or need_emo or need_enroll_align:
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
                    rec.recognize_track(self.db.face_db, track, aligned)
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

            if need_emo and aligned is not None and aligned.size != 0:
                prev = track.get("user_emotion")
                self.emotion_analyzer.maybe_update(track, aligned, self._frame_count)
                if track.get("user_emotion") != prev:
                    emo = track.get("user_emotion")
                    if emo:
                        pct = int(track.get("user_emotion_pct", 0))
                        tid_e = track["id"]
                        if self._last_emotion_by_tid.get(tid_e) != (emo, pct):
                            self._last_emotion_by_tid[tid_e] = (emo, pct)
                            self._queue_event(
                                EmotionUpdated(
                                    track_id=tid_e,
                                    emotion=emo,
                                    confidence_pct=pct,
                                )
                            )

        tracks = self.track_manager.active_tracks()
        visible = self._visible_tracks(tracks)
        if self.enrollment_session.active:
            etid = self.enrollment_session.track_id
            enroll_track = tracks_by_id.get(etid)
            if enroll_track is None or not self._is_verified_human_face(
                enroll_track
            ):
                self.cancel_guided_enrollment()
                self._enrollment["cooldown_until"] = time.time() + ENROLL_COOLDOWN_SEC
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
            frame_width=PROCESS_W,
            frame_height=PROCESS_H,
        )

        ok, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        jpeg_bytes = jpeg.tobytes() if ok else b""

        with self._lock:
            self._latest = _FrameSnapshot(
                frame_count=self._frame_count,
                fps=self._fps_ema,
                jpeg=jpeg_bytes,
                payload=payload,
                camera_ok=True,
            )
        return True, frame

    def _loop(self):
        while not self._stop.is_set():
            t0 = time.perf_counter()
            ok, _ = self._process_one_frame()
            elapsed = time.perf_counter() - t0
            if elapsed > 0:
                inst_fps = 1.0 / elapsed
                self._fps_ema = inst_fps if self._fps_ema <= 0 else (
                    0.85 * self._fps_ema + 0.15 * inst_fps
                )
            if not ok:
                with self._lock:
                    self._latest = _FrameSnapshot(
                        frame_count=self._frame_count,
                        fps=0.0,
                        jpeg=b"",
                        payload=FrameSnapshotOut(),
                        camera_ok=False,
                    )
            delay = max(0.001, 0.033 - elapsed)
            if self._stop.wait(delay):
                break

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
        image_rel = os.path.join(db_mod.CAPTURE_FOLDER, f"{safe}.jpg")
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
            self.db.face_db = self.db.store.build_face_db()
            self.db.save()
            self.response_engine.on_profile_saved(name)
            n_samples = len(self.db.face_db.get(name, []))
            if n_samples == 0:
                return (
                    False,
                    "Could not generate embedding — check lighting and face the camera",
                )
            print(f"[Auty] Enrolled {name} ({n_samples} embedding(s) in database)")
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
