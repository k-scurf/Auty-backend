"""Load merged settings (shared by API server and legacy tools)."""

import json
import os

from utils.paths import (
    ATTENDANCE_LOG_PATH,
    ATTENDANCE_NOTES_PATH,
    AUDIT_LOG_PATH,
    CONSENT_LOG_PATH,
    LOG_PATH,
    MEMORY_PATH,
    PRESENCE_SESSIONS_PATH,
    default_settings_path,
)

DEFAULT_SETTINGS = {
    "use_local_camera": True,
    "camera_index": 0,
    "model_name": "ArcFace",
    "detector_backend": "insightface",
    "face_detector": "insightface",
    "alignment_backend": "insightface",
    "insightface_pack": "buffalo_l",
    "insightface_det_size": 640,
    "detection_mode": "strict",
    "insightface_det_thresh": 0.62,
    "det_min_score_strict": 0.65,
    "det_nms_iou": 0.4,
    "detect_full_resolution": True,
    "detect_performance_mode": False,
    "landmark_min_interocular_ratio": 0.18,
    "landmark_max_interocular_ratio": 0.55,
    "insightface_use_gpu": False,
    "tracker_backend": "bytetrack",
    "bytetrack_track_thresh": 0.58,
    "tracker_min_det_iou": 0.2,
    "bytetrack_match_thresh": 0.8,
    "bytetrack_track_buffer": 15,
    "track_min_stable_frames": 3,
    "guided_enrollment_enabled": True,
    "auto_enrollment_enabled": True,
    "enrollment_min_auto_save": 8,
    "enrollment_min_ready_ui": 6,
    "enrollment_target_total": 25,
    "enrollment_relaxed_pose": True,
    "quality_min_enroll_capture": 35,
    "enrollment_phase_timeout_sec": 12,
    "enrollment_provisional_prefix": "Guest",
    "preprocess_clahe_enabled": True,
    "preprocess_gamma": 1.0,
    "preprocess_clahe_clip_limit": 2.0,
    "preprocess_crop_clahe": False,
    "quality_min_blur_variance": 80,
    "quality_min_recognize": 50,
    "quality_min_enroll": 60,
    "quality_brightness_low": 40,
    "quality_brightness_high": 220,
    "quality_max_yaw_deg": 35,
    "lock_confirm_frames": 6,
    "lock_retain_threshold": 0.40,
    "lock_release_threshold": 0.32,
    "lock_release_streak": 3,
    "unknown_alert_max": 0.35,
    "min_vote_score": 0.35,
    "enroll_threshold_buffer": 0.08,
    "quality_small_face_area_ratio": 0.02,
    "debug_mode": False,
    "debug_draw_landmarks": False,
    "debug_draw_quality": False,
    "debug_draw_track_ids": False,
    "debug_show_distances": False,
    "retinaface_detect_scale": 1.0,
    "retinaface_min_confidence": 0.9,
    "haar_fallback_on_retinaface_fail": False,
    "face_detector_fallback": "mtcnn",
    "recognition_interval": 8,
    "recognition_interval_when_locked": 90,
    "recognition_locked_seconds": 6.0,
    "detect_interval_frames": 15,
    "max_centroid_dist": 50,
    "iou_match_threshold": 0.25,
    "iou_duplicate_threshold": 0.15,
    "nms_iou_threshold": 0.4,
    "max_missing_frames": 5,
    "max_unverified_frames": 2,
    "track_require_verified_det": True,
    "enrollment_min_stable_frames": 10,
    "unknown_min_stable_frames": 8,
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
    "min_face_area_ratio": 0.006,
    "max_face_area_ratio": 0.50,
    "min_aspect_ratio": 0.65,
    "max_aspect_ratio": 1.45,
    "min_laplacian_var": 25.0,
    "min_skin_ratio": 0.04,
    "use_skin_filter": False,
    "use_mediapipe_verify": False,
    "use_strict_detection_filter": True,
    "max_face_detections": 4,
    "merge_duplicate_identity_tracks": True,
    "hud_primary_only": True,
    "hud_enabled": True,
    "hud_card_width": 300,
    "hud_card_height": 140,
    "hud_smooth_alpha": 0.25,
    "hud_draw_bbox": False,
    "hud_fade_in": True,
    "hud_pulse_on_recognize": True,
    "hud_scan_line": False,
    "hud_unknown_auto_snapshot": False,
    "hud_unknown_snapshot_interval": 30,
    "confidence_threshold": 0.48,
    "min_lock_score": 0.62,
    "recognition_streak": 2,
    "score_margin": 0.06,
    "recognition_misses": 4,
    "embedding_history_size": 25,
    "identity_hold_seconds": 1.0,
    "min_vote_ratio": 0.65,
    "vote_min_frames": 6,
    "tracker_type": "kcf",
    "max_embeddings_per_person": 25,
    "learn_threshold": 0.82,
    "learn_streak": 4,
    "learn_interval_seconds": 20,
    "min_new_embedding_distance": 0.02,
    "use_face_alignment": True,
    "debug_scores": False,
    "reset_db_each_run": False,
    "reset_memory_each_run": True,
    "auto_rebuild_db": True,
    "log_file": "logs.txt",
    "personality_enabled": False,
    "memory_file": "memory.json",
    "voice_enabled": False,
    "greeting_bar_enabled": False,
    "greetings_enabled": False,
    "local_llm_enabled": False,
    "async_recognition": True,
    "event_system_enabled": True,
    "greet_stable_frames": 2,
    "ai_states": {
        "face_lost_idle_seconds": 3.0,
        "unknown_alert_seconds": 8.0,
        "engaged_timeout_seconds": 12.0,
        "detecting_lost_quick_seconds": 1.0,
    },
    "attention_switch_margin": 1.25,
    "attention_center_weight": 0.35,
    "attention_unknown_penalty": 0.25,
    "behavior_timing": {},
    "behavior_throttle": {},
    "presence_enabled": True,
    "presence_confirm_frames": 2,
    "presence_confirm_window_seconds": 12.0,
    "kiosk_fast_checkin": True,
    "presence_out_timeout_seconds": 180,
    "presence_checkin_cooldown_seconds": 600,
    "presence_min_lock_score": 0.62,
    "presence_use_confirm_frames_for_filter": True,
    "presence_confidence_history_size": 20,
    "presence_sessions_file": "presence_sessions.json",
    "presence_console_log": True,
    "presence_status_interval_seconds": 30,
    # Attendance / payroll settings
    "attendance_enabled": True,
    "attendance_min_confidence": 0.75,
    "save_clock_in_snapshot": False,
    "location_id": "main",
    "device_id": "default",
    # Data governance
    "data_retention_days": 90,
    "timezone": "America/Chicago",
    # Kiosk
    "kiosk_pin": "1234",
    "kiosk_clock_in_message": "",
    # Consent
    "consent_form_version": "1.0",
    # UI / payroll preferences (stored in settings, not wired to vision logic)
    "company_name": "",
    "default_export_format": "gusto",
    "pay_period_start_day": 1,
    # L3: fail_streak_alert is a UI preference but the enforcement threshold is
    # the module-level FAIL_STREAK_THRESHOLD constant in attendance_tracker.py;
    # wiring them together requires passing settings into AttendanceTracker.
    "fail_streak_alert": 3,
}


def load_settings() -> dict:
    path = default_settings_path()
    if path.exists():
        with open(path, "r") as f:
            data = json.load(f)
        merged = {**DEFAULT_SETTINGS, **data}
    else:
        merged = dict(DEFAULT_SETTINGS)
    merged["memory_file"] = str(MEMORY_PATH)
    merged["log_file"] = str(LOG_PATH)
    pf = merged.get("presence_sessions_file", "presence_sessions.json")
    if not os.path.isabs(str(pf)):
        merged["presence_sessions_path"] = str(PRESENCE_SESSIONS_PATH.parent / pf)
    else:
        merged["presence_sessions_path"] = str(pf)
    merged["attendance_log_path"] = str(ATTENDANCE_LOG_PATH)
    merged["attendance_notes_path"] = str(ATTENDANCE_NOTES_PATH)
    merged["consent_log_path"] = str(CONSENT_LOG_PATH)
    merged["audit_log_path"] = str(AUDIT_LOG_PATH)
    pack_env = os.environ.get("AUTY_INSIGHTFACE_PACK")
    if pack_env:
        merged["insightface_pack"] = pack_env
    elif os.environ.get("RAILWAY_ENVIRONMENT"):
        # buffalo_l needs ~2GB+ RAM; buffalo_sc fits typical Railway plans.
        merged["insightface_pack"] = "buffalo_sc"
        merged["insightface_det_size"] = int(
            os.environ.get("AUTY_INSIGHTFACE_DET_SIZE") or 320
        )
    det_env = os.environ.get("AUTY_INSIGHTFACE_DET_SIZE")
    if det_env:
        merged["insightface_det_size"] = int(det_env)
    # Fix #14: warn loudly about default credentials so operators notice
    if str(merged.get("kiosk_pin", "")) == "1234":
        print(
            "[Auty] WARNING: kiosk_pin is the default '1234'. "
            "Change it via PATCH /api/settings before deploying."
        )
    return merged
