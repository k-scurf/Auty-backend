import re
import tkinter as tk
from tkinter import messagebox
from collections import deque
from PIL import Image, ImageTk

import cv2
import os
import json
import time
import numpy as np

from utils.paths import (
    default_settings_path,
    ensure_directories,
    migrate_legacy_data,
    LOG_PATH,
    MEMORY_PATH,
)

ensure_directories()
migrate_legacy_data()

import face_detection
import recognition as rec
import database as db_mod
import tracking as track_engine
import ui_overlay
import camera as camera_mod
from attention_manager import AttentionManager
from timing_controller import TimingController
from event_system import (
    AttentionShifted,
    EventBus,
    FaceDetected,
    FaceLost,
    FaceRecognized,
    StateChanged,
    UnknownFaceDetected,
    UserCommandIntent,
)
from memory import Memory
from response_engine import ResponseEngine
from state_machine import AIState, FSMContext, StateMachine
import recognition_worker
from ui.image_fit import bgr_to_photo_cover, bgr_to_photo_cover_rounded
from ui.shell import build_shell
from ui.theme import (
    ENROLL_COOLDOWN_SEC,
    ENROLL_FRAME_GAP,
    ENROLL_SAMPLE_COUNT,
    FEED_H,
    FEED_W,
    FONT,
    FONT_BOLD,
    FONT_SMALL,
    PREVIEW_ZOOM_SIZE,
    PROCESS_H,
    PROCESS_W,
    SNAPSHOT_H,
    SNAPSHOT_W,
    THEME,
    make_button,
    make_label,
)

SETTINGS_FILE = None  # resolved via utils.paths.default_settings_path()
DEFAULT_SETTINGS = {
    "camera_index": 0,
    "model_name": "ArcFace",
    "detector_backend": "opencv",
    "recognition_interval": 8,
    "recognition_interval_when_locked": 90,
    "recognition_locked_seconds": 6.0,
    "detect_interval_frames": 15,
    "max_centroid_dist": 50,
    "iou_match_threshold": 0.25,
    "iou_duplicate_threshold": 0.15,
    "nms_iou_threshold": 0.4,
    "max_missing_frames": 10,
    "bbox_smooth_alpha": 0.3,
    "tracker_reinit_iou": 0.15,
    "predict_frames": 2,
    "haar_scale_factor": 1.1,
    "haar_min_neighbors": 7,
    "haar_min_size": 60,
    "min_confirm_frames": 1,
    "max_confirm_misses": 15,
    "min_face_width": 50,
    "min_face_height": 50,
    "min_face_area_ratio": 0.008,
    "max_face_area_ratio": 0.50,
    "min_aspect_ratio": 0.65,
    "max_aspect_ratio": 1.45,
    "min_laplacian_var": 25.0,
    "min_skin_ratio": 0.04,
    "use_skin_filter": False,
    "use_mediapipe_verify": False,
    "use_strict_detection_filter": True,
    "max_face_detections": 3,
    "merge_duplicate_identity_tracks": True,
    "hud_primary_only": True,
    "hud_enabled": True,
    "hud_card_width": 300,
    "hud_card_height": 140,
    "hud_smooth_alpha": 0.25,
    "hud_draw_bbox": True,
    "hud_fade_in": True,
    "hud_pulse_on_recognize": True,
    "hud_scan_line": True,
    "hud_unknown_auto_snapshot": True,
    "hud_unknown_snapshot_interval": 30,
    "hud_distance_estimate": False,
    "hud_eye_contact": False,
    "confidence_threshold": 0.52,
    "min_lock_score": 0.78,
    "recognition_streak": 2,
    "score_margin": 0.03,
    "recognition_misses": 4,
    "embedding_history_size": 25,
    "identity_hold_seconds": 1.0,
    "min_vote_ratio": 0.55,
    "vote_min_frames": 5,
    "tracker_type": "kcf",
    "max_embeddings_per_person": 25,
    "learn_threshold": 0.82,
    "learn_streak": 4,
    "learn_interval_seconds": 20,
    "min_new_embedding_distance": 0.02,
    "use_face_alignment": False,
    "debug_scores": False,
    "reset_db_each_run": False,
    "reset_memory_each_run": True,
    "auto_rebuild_db": True,
    "log_file": "logs.txt",
    "personality_enabled": False,
    "memory_file": "memory.json",
    "voice_enabled": False,
    "tts_enabled": False,
    "greeting_bar_enabled": False,
    "greetings_enabled": False,
    "local_llm_enabled": False,
    "ollama_base_url": "http://127.0.0.1:11434",
    "ollama_model": "llama3.2:1b",
    "auto_converse_after_greet": True,
    "ui_effects_enabled": True,
    "voice_commands_enabled": False,
    "voice_listen_timeout": 4.0,
    "voice_phrase_limit": 6.0,
    "voice_command_cooldown": 1.5,
    "voice_language": "en-US",
    "voice_prefer_offline": False,
    "async_recognition": True,
    "recognition_locked_seconds": 10.0,
    "memory_save_delay_seconds": 5.0,
    "event_system_enabled": True,
    "ai_states": {
        "face_lost_idle_seconds": 3.0,
        "unknown_alert_seconds": 8.0,
        "engaged_timeout_seconds": 12.0,
        "detecting_lost_quick_seconds": 1.0,
    },
    "attention_switch_margin": 1.25,
    "attention_center_weight": 0.35,
    "attention_unknown_penalty": 0.25,
    "behavior_timing": {
        "detecting_max_seconds": 2.0,
        "engaged_after_present_seconds": 3.0,
        "idle_after_no_face_seconds": 5.0,
        "familiar_after_recognized_seconds": 10.0,
        "unknown_alert_ramp_seconds": 12.0,
        "recency_attention_boost_seconds": 1.5,
        "familiar_greeting_delay_ms": 180,
    },
    "behavior_throttle": {
        "greeting_cooldown_seconds": 20.0,
        "voice_min_gap_seconds": 4.0,
        "event_cooldown_seconds": 2.0,
        "batch_window_ms": 150.0,
    },
}

def load_settings():
    path = default_settings_path()
    if path.exists():
        with open(path, "r") as f:
            data = json.load(f)
        merged = {**DEFAULT_SETTINGS, **data}
    else:
        merged = dict(DEFAULT_SETTINGS)
    merged["memory_file"] = str(MEMORY_PATH)
    merged["log_file"] = str(LOG_PATH)
    return merged


SETTINGS = load_settings()
rec.configure(SETTINGS)
db = db_mod.FaceDatabase(SETTINGS)
event_bus = EventBus()
fsm = StateMachine(SETTINGS)
attention_mgr = AttentionManager(SETTINGS)
timing_controller = TimingController(SETTINGS)
fsm.set_timing_controller(timing_controller)
attention_mgr.set_timing_controller(timing_controller)
memory = Memory(SETTINGS, db)
response_engine = ResponseEngine(SETTINGS, event_bus, fsm, memory)
rec_worker = recognition_worker.RecognitionWorker()
EVENT_SYSTEM_ENABLED = bool(SETTINGS.get("event_system_enabled", True))
VOICE_ENABLED = bool(SETTINGS.get("voice_enabled", False))
_prev_track_ids: set = set()
_recognized_emitted: set = set()
_recognized_names_session: set = set()
_unknown_emitted: set = set()
_camera_loop_busy = False
ASYNC_RECOGNITION = bool(SETTINGS.get("async_recognition", True))
db.configure()

RECOGNITION_INTERVAL = int(SETTINGS["recognition_interval"])
RECOGNITION_INTERVAL_LOCKED = int(
    SETTINGS.get("recognition_interval_when_locked", 90)
)
RECOGNITION_LOCKED_SECONDS = float(
    SETTINGS.get("recognition_locked_seconds", 6.0)
)
GREET_STABLE_FRAMES = int(SETTINGS.get("greet_stable_frames", 2))
EMBEDDING_HISTORY_SIZE = int(SETTINGS.get("embedding_history_size", 20))
RECOGNITION_THRESHOLD = float(SETTINGS["confidence_threshold"])
RECOGNITION_STREAK = int(SETTINGS.get("recognition_streak", 3))
SCORE_MARGIN = float(SETTINGS.get("score_margin", 0.05))
RECOGNITION_MISSES = int(SETTINGS.get("recognition_misses", 3))
MAX_EMBEDDINGS_PER_PERSON = int(SETTINGS.get("max_embeddings_per_person", 25))
LEARN_THRESHOLD = float(SETTINGS.get("learn_threshold", 0.85))
LEARN_STREAK = int(SETTINGS.get("learn_streak", 5))
LEARN_INTERVAL_SECONDS = float(SETTINGS.get("learn_interval_seconds", 20))
MIN_NEW_EMBEDDING_DISTANCE = float(SETTINGS.get("min_new_embedding_distance", 0.02))
DEBUG_SCORES = bool(SETTINGS.get("debug_scores", False))
RESET_DB_EACH_RUN = bool(SETTINGS.get("reset_db_each_run", False))
RESET_MEMORY_EACH_RUN = bool(SETTINGS.get("reset_memory_each_run", True))

if not RESET_DB_EACH_RUN:
    db.load()
else:
    db.face_db = {}

# =========================================
# ENROLLMENT STATE
# =========================================

enrollment = {
    "collecting": False,
    "samples": [],
    "pending": None,
    "pending_embeddings": [],
    "cooldown_until": 0.0,
    "target_tid": None,
    "gap_counter": 0,
}

# =========================================
# ENROLLMENT HELPERS
# =========================================

def blur_score(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var()


def pick_best_crop(crops):
    return max(crops, key=blur_score)


def sanitize_name(name):
    safe = re.sub(r"[^\w\-]", "_", name.strip())
    return safe or "unknown"


def padded_crop(frame, x, y, w, h, pad_ratio=0.25):
    return rec.padded_crop(frame, x, y, w, h, pad_ratio)


def _create_tracker():
    kind = str(SETTINGS.get("tracker_type", "kcf")).lower()
    if kind == "csrt":
        if hasattr(cv2, "TrackerCSRT_create"):
            return cv2.TrackerCSRT_create()
        return cv2.legacy.TrackerCSRT_create()
    if hasattr(cv2, "TrackerKCF_create"):
        return cv2.TrackerKCF_create()
    return cv2.legacy.TrackerKCF_create()


def new_face_track(track_id):
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
        "embedding_history": deque(maxlen=EMBEDDING_HISTORY_SIZE),
        "vote_history": deque(maxlen=EMBEDDING_HISTORY_SIZE),
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
    }


def maybe_learn_embedding(name, embedding, score, track):
    if name == "UNKNOWN" or score is None or score < LEARN_THRESHOLD:
        return

    if track.get("stable_count", 0) < LEARN_STREAK:
        return

    now = time.time()
    if (now - track.get("last_learned_at", 0)) < LEARN_INTERVAL_SECONDS:
        return

    if not db.embedding_is_new(name, embedding):
        return

    if db.add_embedding(name, embedding):
        db.save()
        track["last_learned_at"] = now
        if DEBUG_SCORES:
            rec.log_recognition(f"learned new pose for {name}")


def reset_collection():
    enrollment["collecting"] = False
    enrollment["samples"] = []
    enrollment["target_tid"] = None
    enrollment["gap_counter"] = 0


def finalize_enrollment():
    enrollment["pending"] = pick_best_crop(enrollment["samples"]).copy()
    enrollment["pending_embeddings"] = []
    for crop in enrollment["samples"]:
        aligned = crop
        if not rec.is_aligned_crop(crop):
            h, w = crop.shape[:2]
            aligned = rec.align_face(crop, 0, 0, w, h)
        emb = rec.extract_embedding(aligned, already_aligned=rec.is_aligned_crop(aligned))
        if emb is not None:
            enrollment["pending_embeddings"].append(emb)
    reset_collection()
    show_pending_preview(enrollment["pending"])
    set_form_enabled(True)


def start_enrollment_collection(track_id, face_crop):
    enrollment["collecting"] = True
    enrollment["target_tid"] = track_id
    enrollment["samples"] = [face_crop.copy()]
    enrollment["gap_counter"] = 0


def process_enrollment(unknown_faces, active_tids):
    if enrollment["pending"] is not None:
        return

    if enrollment["collecting"] and enrollment["target_tid"] not in active_tids:
        reset_collection()
        return

    if time.time() < enrollment["cooldown_until"]:
        return

    if not unknown_faces:
        return

    area, tid, crop = max(unknown_faces, key=lambda item: item[0])

    if not enrollment["collecting"]:
        start_enrollment_collection(tid, crop)
        return

    if tid != enrollment["target_tid"]:
        return

    enrollment["gap_counter"] += 1
    if enrollment["gap_counter"] >= ENROLL_FRAME_GAP:
        enrollment["gap_counter"] = 0
        enrollment["samples"].append(crop.copy())
        if len(enrollment["samples"]) >= ENROLL_SAMPLE_COUNT:
            finalize_enrollment()


# =========================================
# MAIN WINDOW
# =========================================

preview_zoom_window = None
voice_listener = None

root = tk.Tk()
shell = None


def set_form_enabled(enabled):
    state = "normal" if enabled else "disabled"
    for widget in (
        shell.name_entry,
        shell.age_entry,
        shell.status_entry,
        shell.save_btn,
        shell.skip_btn,
    ):
        widget.config(state=state)


def open_preview_zoom(event=None):
    if enrollment["pending"] is None:
        return

    global preview_zoom_window
    if preview_zoom_window is not None and preview_zoom_window.winfo_exists():
        preview_zoom_window.lift()
        preview_zoom_window.focus_force()
        return

    win = tk.Toplevel(root)
    preview_zoom_window = win
    win.title("Face preview")
    win.configure(bg=THEME["bg_root"])
    win.transient(root)
    win.resizable(False, False)

    outer = tk.Frame(win, bg=THEME["border"], padx=1, pady=1)
    outer.pack(padx=20, pady=(20, 8))

    inner = tk.Frame(outer, bg=THEME["bg_card"])
    inner.pack()

    photo = bgr_to_photo_cover_rounded(
        enrollment["pending"], PREVIEW_ZOOM_SIZE, PREVIEW_ZOOM_SIZE, radius=16
    )
    zoom_label = tk.Label(inner, image=photo, bg=THEME["bg_card"], cursor="hand2")
    zoom_label.image = photo
    zoom_label.pack(padx=10, pady=10)
    zoom_label.bind("<Button-1>", lambda e: win.destroy())

    hint = tk.Label(
        win,
        text="Press Esc or click image to close",
        font=FONT_SMALL,
        fg=THEME["text_muted"],
        bg=THEME["bg_root"],
    )
    hint.pack(pady=(0, 8))

    close_btn = tk.Button(
        win,
        text="Close",
        command=win.destroy,
        font=FONT_BOLD,
        bg=THEME["accent"],
        fg="#0b0f14",
        activebackground=THEME["accent_light"],
        relief="flat",
        cursor="hand2",
        padx=20,
        pady=8,
        bd=0,
    )
    close_btn.pack(pady=(0, 16))

    win.bind("<Escape>", lambda e: win.destroy())
    win.protocol("WM_DELETE_WINDOW", win.destroy)

    win.update_idletasks()
    w = win.winfo_width()
    h = win.winfo_height()
    x = root.winfo_x() + (root.winfo_width() - w) // 2
    y = root.winfo_y() + (root.winfo_height() - h) // 2
    win.geometry(f"+{x}+{y}")


def show_pending_preview(bgr_crop):
    photo = bgr_to_photo_cover_rounded(bgr_crop, SNAPSHOT_W, SNAPSHOT_H, radius=10)
    shell.snapshot.set_image(photo)
    shell.preview_hint.pack(pady=(0, 8))
    shell.enroll_section_label.config(text="READY TO ENROLL")


def clear_pending_preview():
    global preview_zoom_window
    if preview_zoom_window is not None and preview_zoom_window.winfo_exists():
        preview_zoom_window.destroy()
    preview_zoom_window = None

    shell.snapshot.clear("Waiting for face…")
    shell.preview_hint.pack_forget()
    shell.enroll_section_label.config(text="NEW FRIEND")


def clear_form():
    shell.name_entry.delete(0, tk.END)
    shell.age_entry.delete(0, tk.END)
    shell.status_entry.delete(0, tk.END)


def skip_enrollment():
    enrollment["pending"] = None
    enrollment["cooldown_until"] = time.time() + ENROLL_COOLDOWN_SEC
    reset_collection()
    clear_pending_preview()
    clear_form()
    set_form_enabled(False)


def save_profile():
    if enrollment["pending"] is None:
        messagebox.showerror("Error", "No face ready to enroll")
        return

    name = shell.name_entry.get().strip()
    if not name:
        messagebox.showerror("Error", "Name is required")
        return

    safe_name = sanitize_name(name)
    image_rel = os.path.join(db_mod.CAPTURE_FOLDER, f"{safe_name}.jpg")
    image_path = image_rel

    cv2.imwrite(image_path, enrollment["pending"])

    profile = {
        "name": name,
        "age": shell.age_entry.get(),
        "status": shell.status_entry.get(),
        "image": image_rel,
    }

    db.save_profile(name, profile)
    response_engine.on_profile_saved(name)

    try:
        for emb in enrollment.get("pending_embeddings", []):
            db.add_embedding(name, emb)
        saved_bgr = cv2.imread(image_path)
        if saved_bgr is not None:
            sh, sw = saved_bgr.shape[:2]
            embedding = rec.extract_embedding(
                rec.align_face(saved_bgr, 0, 0, sw, sh)
            )
            if embedding:
                db.add_embedding(name, embedding)
        db.save()
    except Exception:
        messagebox.showerror("Embedding Error", "Could not generate embedding")
        return

    enrollment["pending"] = None
    enrollment["pending_embeddings"] = []
    enrollment["cooldown_until"] = time.time() + ENROLL_COOLDOWN_SEC
    reset_collection()
    clear_pending_preview()
    clear_form()
    set_form_enabled(False)
    shell.activity_log.log_enrolled(name)
    messagebox.showinfo("Welcome!", f"{name} is all set — nice to meet them!")


shell = build_shell(root, on_snapshot_click=open_preview_zoom)
shell.save_btn.config(command=save_profile)
shell.skip_btn.config(command=skip_enrollment)
shell.preview_hint.bind("<Button-1>", open_preview_zoom)

camera_label = shell.camera_label
feed_card = shell.feed_card

if VOICE_ENABLED:
    import ui_waveform
    import voice_commands
    import voice_command_handler

    voice_section = shell.profile_tab
    make_label(voice_section, "VOICE", style="section", anchor="w", pady=(0, 6))

    waveform = ui_waveform.WaveformPanel(voice_section, THEME)

    voice_heard_var = tk.StringVar(
        value='Say: "Who am I?" · "Help"'
    )
    tk.Label(
        voice_section,
        textvariable=voice_heard_var,
        font=FONT_SMALL,
        fg=THEME["text_muted"],
        bg=THEME["bg_panel"],
        anchor="w",
        wraplength=300,
        justify="left",
    ).pack(fill="x", pady=(4, 8))

    voice_btn_row = tk.Frame(voice_section, bg=THEME["bg_panel"])
    voice_btn_row.pack(fill="x")

    continuous_listen = tk.BooleanVar(value=False)

    def handle_voice_command(intent: str, raw_text: str):
        if EVENT_SYSTEM_ENABLED:
            voice_heard_var.set(f"Heard: {raw_text[:48]}")
            _queue_event(UserCommandIntent(intent=intent, raw_text=raw_text))
            _process_frame_events()
            return
        voice_command_handler.handle_intent(
            intent,
            raw_text,
            brain=response_engine,
            track_manager=track_manager,
            profiles=db.load_profiles(),
            voice_heard_var=voice_heard_var,
        )

    def on_voice_ui_state(mode: str):
        if response_engine.voice.is_speaking:
            return
        waveform.set_mode(mode)

    if SETTINGS.get("voice_commands_enabled"):
        voice_listener = voice_commands.VoiceCommandListener(
            SETTINGS, handle_voice_command, on_state=on_voice_ui_state
        )

    def on_tts_state(mode: str):
        if mode == "speaking":
            waveform.set_mode("speaking")
        elif continuous_listen.get():
            waveform.set_mode("listening")
        else:
            waveform.set_mode("idle")

    response_engine.voice.add_state_listener(on_tts_state)

    def push_to_talk():
        if voice_listener:
            voice_listener.listen_push_to_talk(
                is_speaking=response_engine.voice.is_speaking
            )

    def toggle_continuous_listen():
        if not voice_listener:
            return
        on = not continuous_listen.get()
        continuous_listen.set(on)
        voice_listener.set_continuous(
            on, is_speaking=response_engine.voice.is_speaking
        )
        if not on and not response_engine.voice.is_speaking:
            waveform.set_mode("idle")

    make_button(
        voice_btn_row,
        "Tap to talk",
        push_to_talk,
        side="left",
        expand=True,
        fill="x",
        padx=(0, 6),
    )

    make_button(
        voice_btn_row,
        "Always listen",
        toggle_continuous_listen,
        secondary=True,
        side="left",
        expand=True,
        fill="x",
        padx=(6, 0),
    )

set_form_enabled(False)

# =========================================
# CAMERA SETUP
# =========================================

camera_stream = camera_mod.CameraStream(SETTINGS, PROCESS_W, PROCESS_H)
face_cascade = face_detection.create_haar_cascade()
hud_renderer = ui_overlay.HUDRenderer(SETTINGS, db_mod.CAPTURE_FOLDER)
frame_count = 0
track_manager = None


def reset_session():
    """Clear per-run recognition and enrollment state (each app launch)."""
    global frame_count, track_manager, _prev_track_ids, _recognized_emitted, _unknown_emitted, _recognized_names_session

    if RESET_DB_EACH_RUN:
        db.reset()
    if RESET_MEMORY_EACH_RUN:
        memory.reset()

    frame_count = 0
    _prev_track_ids = set()
    _recognized_emitted = set()
    _recognized_names_session = set()
    _unknown_emitted = set()
    fsm.state = AIState.IDLE
    fsm.ctx = FSMContext()
    attention_mgr._current_primary = None
    timing_controller.reset()
    response_engine.sequences.cancel()
    if track_manager is not None:
        track_manager.reset()
    enrollment["collecting"] = False
    enrollment["samples"] = []
    enrollment["pending"] = None
    enrollment["pending_embeddings"] = []
    enrollment["cooldown_until"] = 0.0
    enrollment["target_tid"] = None
    enrollment["gap_counter"] = 0
    clear_pending_preview()
    clear_form()
    set_form_enabled(False)
    if shell is not None:
        shell.activity_log.clear()


# =========================================
# CAMERA LOOP
# =========================================


def _track_is_known_stable(track: dict) -> bool:
    return (
        track.get("locked_name", "UNKNOWN") != "UNKNOWN"
        and track.get("stable_count", 0) >= GREET_STABLE_FRAMES
    )


def _track_is_unknown_stable(track: dict) -> bool:
    return (
        track.get("locked_name", "UNKNOWN") == "UNKNOWN"
        and track.get("stable_count", 0) >= GREET_STABLE_FRAMES
    )


def _bump_recognition_stability(track: dict, *, had_embedding: bool):
    """Advance stability after a recognition cycle (known or unknown)."""
    if not had_embedding:
        track["stable_count"] = 0
        return
    track["stable_count"] = min(track.get("stable_count", 0) + 1, 64)


def _apply_async_recognition(tid: int, embedding, tracks_by_id: dict):
    track = tracks_by_id.get(tid)
    if track is None or not db.face_db:
        return
    had_emb = embedding is not None
    rec.apply_embedding_to_track(db.face_db, track, embedding)
    _bump_recognition_stability(track, had_embedding=had_emb)
    if had_emb and track.get("locked_name", "UNKNOWN") != "UNKNOWN":
        emb = track.get("last_embedding")
        if emb is not None:
            maybe_learn_embedding(
                track["locked_name"],
                emb,
                track.get("locked_score"),
                track,
            )


def _should_run_recognition(track: dict, frame_count: int) -> bool:
    locked = track.get("locked_name", "UNKNOWN")
    if locked == "UNKNOWN":
        return (
            frame_count - track.get("last_recognition_frame", -999)
            >= RECOGNITION_INTERVAL
        )
    if not _track_is_known_stable(track):
        return (
            frame_count - track.get("last_recognition_frame", -999)
            >= RECOGNITION_INTERVAL
        )
    now = time.time()
    if now - track.get("last_recognition_time", 0.0) < RECOGNITION_LOCKED_SECONDS:
        return False
    if (
        frame_count - track.get("last_recognition_frame", -999)
        < RECOGNITION_INTERVAL_LOCKED
    ):
        return False
    return True


def _queue_event(event):
    event.timestamp = time.time()
    event.frame_count = frame_count
    event_bus.emit(event)


def _emit_track_lifecycle(active_tids: set):
    global _prev_track_ids, _recognized_emitted, _unknown_emitted, _recognized_names_session
    for tid in active_tids - _prev_track_ids:
        track = next((t for t in track_manager.active_tracks() if t["id"] == tid), None)
        bbox = (0, 0, 0, 0)
        if track:
            bbox = track.get("smooth_bbox") or track.get("bbox", bbox)
        _queue_event(FaceDetected(track_id=tid, bbox=bbox))
    for tid in _prev_track_ids - active_tids:
        _queue_event(FaceLost(track_id=tid))
        _recognized_emitted = {k for k in _recognized_emitted if k[0] != tid}
        _unknown_emitted.discard(tid)
    _prev_track_ids = set(active_tids)


def _log_identity_event(kind: str, track: dict, name: str = "", confidence: float = 0.0):
    """Append to sidebar activity log (UI thread only)."""
    if shell is None:
        return
    when = time.time()
    if kind == "known":
        shell.activity_log.log_known(name, confidence, when=when)
    elif kind == "unknown":
        shell.activity_log.log_unknown(when=when, track_id=track.get("id"))


def _sync_identity_events(tracks):
    for track in tracks:
        tid = track["id"]
        name = track.get("locked_name", "UNKNOWN")
        if name != "UNKNOWN" and _track_is_known_stable(track):
            if name not in _recognized_names_session:
                conf = float(track.get("locked_score", 0) or 0)
                _queue_event(
                    FaceRecognized(
                        track_id=tid,
                        name=name,
                        confidence=conf,
                    )
                )
                _recognized_names_session.add(name)
                _recognized_emitted.add((tid, name))
                _log_identity_event("known", track, name=name, confidence=conf)
        elif _track_is_unknown_stable(track) and tid not in _unknown_emitted:
            _queue_event(
                UnknownFaceDetected(
                    track_id=tid,
                    confidence=float(track.get("locked_score", 0) or 0),
                )
            )
            _unknown_emitted.add(tid)
            _log_identity_event("unknown", track)


def _process_frame_events():
    events = event_bus.drain()
    tracks = track_manager.active_tracks() if track_manager else []
    primary_tid = attention_mgr.primary_track_id
    primary_name = "UNKNOWN"
    primary_stable = False
    if primary_tid is not None:
        pt = next((t for t in tracks if t["id"] == primary_tid), None)
        if pt:
            primary_name = pt.get("locked_name", "UNKNOWN")
            primary_stable = _track_is_known_stable(pt)
    fsm.update_context(
        has_faces=bool(tracks),
        active_track_ids={t["id"] for t in tracks},
        primary_track_id=primary_tid,
        primary_name=primary_name,
        primary_stable=primary_stable,
    )
    transitions = fsm.process_events(events)
    events.extend(transitions)
    event_bus.dispatch(events)


def update_camera():
    global frame_count, _camera_loop_busy

    if _camera_loop_busy:
        camera_label.after(5, update_camera)
        return

    t0 = time.perf_counter()
    _camera_loop_busy = True

    try:
        ret, frame = camera_stream.read()
        if not ret:
            return

        track_manager.step(frame, frame_count)

        active_tids = set()
        unknown_faces = []
        profiles = db.load_profiles()
        tracks_by_id = {t["id"]: t for t in track_manager.active_tracks()}

        for tid, embedding in rec_worker.poll():
            _apply_async_recognition(tid, embedding, tracks_by_id)

        for track in track_manager.active_tracks():
            tid = track["id"]
            active_tids.add(tid)

            x, y, w, h = track.get("smooth_bbox") or track.get("bbox", (0, 0, 0, 0))

            need_rec = bool(db.face_db) and _should_run_recognition(track, frame_count)
            aligned = None
            if need_rec:
                aligned = rec.align_face(frame, x, y, w, h)
            elif _track_is_known_stable(track):
                track["miss_count"] = 0

            if need_rec and aligned is not None and aligned.size != 0:
                if ASYNC_RECOGNITION:
                    if rec_worker.submit(tid, aligned):
                        track["last_recognition_frame"] = frame_count
                        track["last_recognition_time"] = time.time()
                else:
                    track["last_recognition_frame"] = frame_count
                    track["last_recognition_time"] = time.time()
                    rec.recognize_track(db.face_db, track, aligned)
                    _bump_recognition_stability(
                        track, had_embedding=track.get("last_embedding") is not None
                    )
                    if track.get("locked_name", "UNKNOWN") != "UNKNOWN":
                        emb = track.get("last_embedding")
                        if emb is not None:
                            maybe_learn_embedding(
                                track["locked_name"],
                                emb,
                                track.get("locked_score"),
                                track,
                            )

            if track.get("locked_name", "UNKNOWN") == "UNKNOWN" and aligned is not None and aligned.size != 0:
                unknown_faces.append((w * h, tid, aligned.copy()))

        tracks = track_manager.active_tracks()
        _emit_track_lifecycle(active_tids)

        prev_primary = attention_mgr.primary_track_id
        attn = attention_mgr.select(tracks, (PROCESS_W, PROCESS_H))
        primary_track = attn.primary_track
        primary_name = (
            primary_track.get("locked_name", "UNKNOWN") if primary_track else "UNKNOWN"
        )
        timing_controller.update(
            tracks, attn.primary_track_id, primary_name
        )
        familiar = timing_controller.is_familiar_session(primary_name)

        response_engine.set_frame_context(
            tracks,
            profiles,
            frame_count,
            primary_track_id=attn.primary_track_id,
            secondary_track_ids=attn.secondary_track_ids,
            familiar=familiar,
        )

        _sync_identity_events(tracks)

        if attention_mgr.primary_track_id != prev_primary:
            _queue_event(
                AttentionShifted(
                    previous_track_id=prev_primary,
                    track_id=attention_mgr.primary_track_id,
                )
            )

        if EVENT_SYSTEM_ENABLED:
            _process_frame_events()

        frame, ctx = response_engine.process_frame(frame, primary_track)
        memory.save()

        frame = hud_renderer.draw_all(
            frame,
            tracks,
            profiles,
            frame_count,
            brain_ctx=ctx,
            primary_track_id=attention_mgr.primary_track_id,
        )

        process_enrollment(unknown_faces, active_tids)

        frame_count += 1

        display = frame
        dw, dh = shell.display_w, shell.display_h
        if dw > 0 and dh > 0:
            display = cv2.resize(frame, (dw, dh), interpolation=cv2.INTER_LINEAR)

        rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        imgtk = ImageTk.PhotoImage(image=Image.fromarray(rgb))
        camera_label.imgtk = imgtk
        camera_label.configure(image=imgtk)
    finally:
        _camera_loop_busy = False
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        delay = max(1, int(33 - elapsed_ms))
        camera_label.after(delay, update_camera)


# =========================================
# START APP
# =========================================

def on_app_close():
    if voice_listener is not None:
        voice_listener.set_continuous(False)
    rec_worker.shutdown()
    memory.save(force=True)
    if RESET_DB_EACH_RUN:
        db.reset()
    camera_stream.release()
    cv2.destroyAllWindows()
    root.destroy()


root.protocol("WM_DELETE_WINDOW", on_app_close)

track_manager = track_engine.FaceTrackManager(
    SETTINGS,
    face_cascade,
    _create_tracker,
    new_face_track,
)
response_engine.set_track_manager(track_manager)
if EVENT_SYSTEM_ENABLED:
    def _log_state_change(event):
        if isinstance(event, StateChanged):
            print(
                f"[Auty FSM] {event.previous_state} -> {event.new_state} ({event.reason})"
            )

    event_bus.subscribe(StateChanged, _log_state_change)

reset_session()
update_camera()

root.mainloop()
