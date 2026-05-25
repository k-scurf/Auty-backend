"""API request/response models."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------

class ActiveEmployeeOut(BaseModel):
    employee_id: str
    name: str
    clock_in_ts: float
    clock_in_utc: str
    duration_seconds: float
    location_id: str


class AttendanceEventOut(BaseModel):
    id: str
    employee_id: str
    name: str
    event: str  # CLOCK_IN | CLOCK_OUT
    timestamp_utc: str
    timestamp_ts: float
    location_id: str
    confidence: float
    device_id: str
    snapshot_path: Optional[str] = None
    notes: List[dict] = Field(default_factory=list)


class AttendanceAlertOut(BaseModel):
    type: str
    name: str
    ts: float
    detail: str = ""


class AttendanceStatusOut(BaseModel):
    clocked_in: List[ActiveEmployeeOut] = Field(default_factory=list)
    recent_events: List[AttendanceEventOut] = Field(default_factory=list)
    alerts: List[AttendanceAlertOut] = Field(default_factory=list)


class ScheduleDayOut(BaseModel):
    working: bool = False
    start: Optional[str] = None
    end: Optional[str] = None


class WeeklyScheduleIn(BaseModel):
    name: str = ""
    timezone: str = "America/Chicago"
    days: Dict[str, ScheduleDayOut] = Field(default_factory=dict)


class WeeklyScheduleOut(WeeklyScheduleIn):
    employee_id: str


class TodayAttendanceRowOut(BaseModel):
    employee_id: str
    name: str
    status: str
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    timezone: str = "America/Chicago"
    clock_in_ts: Optional[float] = None
    clock_out_ts: Optional[float] = None
    clock_in_time: Optional[str] = None
    clock_out_time: Optional[str] = None
    hours: Optional[float] = None
    has_schedule: bool = False
    day_off: bool = False
    alert: Optional[str] = None


class TodayAttendanceStatusOut(BaseModel):
    date: str
    timezone: str = "America/Chicago"
    rows: List[TodayAttendanceRowOut] = Field(default_factory=list)


class AttendanceNoteCreate(BaseModel):
    event_id: str
    note: str
    manager: str = "manager"


class ExportRequest(BaseModel):
    format: str  # gusto | adp | square
    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD
    location_id: Optional[str] = None


class ExportPreviewOut(BaseModel):
    row_count: int
    total_hours: float
    employee_count: int
    format: str
    start_date: str
    end_date: str


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

class ConsentCreate(BaseModel):
    employee_id: str
    name: str
    ip_address: str = ""
    form_version: str = "1.0"


class ConsentStatusOut(BaseModel):
    employee_id: str
    consented: bool
    timestamp_utc: Optional[str] = None
    form_version: Optional[str] = None


class TrackOut(BaseModel):
    id: int
    bbox: List[int]
    name: str = "UNKNOWN"
    confidence: float = 0.0
    known: bool = False
    stability_pct: int = 0
    quality_score: float = 0.0
    blur_score: float = 0.0
    vote_ratio: float = 0.0
    distance: Optional[float] = None
    pose_yaw: float = 0.0
    lock_state: str = "unknown"
    match_margin: float = 0.0
    reject_reason: str = ""
    best_candidate: str = ""


class LogEntryOut(BaseModel):
    ts: float
    type: str
    name: Optional[str] = None
    confidence: Optional[float] = None
    track_id: Optional[int] = None
    detail: Optional[str] = None


class EnrollmentPendingOut(BaseModel):
    ready: bool = False
    track_id: Optional[int] = None
    image_b64: Optional[str] = None


class EnrollmentProgressOut(BaseModel):
    active: bool = False
    phase: str = ""
    instruction: str = ""
    captured: int = 0
    target: int = 0
    min_auto: int = 8
    min_ready: int = 6
    percent: float = 0.0
    rejected_blur: int = 0
    rejected_quality: int = 0
    rejected_pose: int = 0
    rejected_embed: int = 0
    tick_count: int = 0
    last_reject_reason: Optional[str] = None
    ready_to_save: bool = False
    preview_b64: Optional[str] = None
    auto_committed: bool = False
    provisional_name: Optional[str] = None
    phase_counts: Dict[str, int] = Field(default_factory=dict)
    phase_targets: Dict[str, int] = Field(default_factory=dict)
    phases: List[str] = Field(default_factory=list)


class PresencePersonOut(BaseModel):
    name: str
    status: str = "IN"
    since_ts: float = 0.0
    last_seen_ts: float = 0.0
    confidence_avg: Optional[float] = None


class PresenceActivityOut(BaseModel):
    name: str
    last_seen_ts: float
    event: str


class PresenceOut(BaseModel):
    in_office: List[PresencePersonOut] = Field(default_factory=list)
    recent_activity: List[PresenceActivityOut] = Field(default_factory=list)
    today_totals: Dict[str, float] = Field(default_factory=dict)
    events_tail: List[PresenceActivityOut] = Field(default_factory=list)


class FrameSnapshotOut(BaseModel):
    frame_count: int = 0
    fps: float = 0.0
    fsm_state: str = "IDLE"
    mood: str = "Calm"
    status_line: str = ""
    primary_track_id: Optional[int] = None
    tracks: List[TrackOut] = Field(default_factory=list)
    log_tail: List[LogEntryOut] = Field(default_factory=list)
    enrollment: EnrollmentPendingOut = Field(default_factory=EnrollmentPendingOut)
    enrollment_progress: EnrollmentProgressOut = Field(
        default_factory=EnrollmentProgressOut
    )
    presence: Optional[PresenceOut] = None
    # Last few attendance events, included so the kiosk can react at WS rate
    # (~12 fps) without waiting for the 2-second HTTP attendance poll.
    recent_attendance: List[AttendanceEventOut] = Field(default_factory=list)
    frame_width: int = 960
    frame_height: int = 540
    process_fps: float = 0.0
    camera_fps: float = 0.0


class HealthOut(BaseModel):
    camera_ok: bool
    db_loaded: bool
    face_count: int
    profile_count: int
    fps: float
    uptime_seconds: float
    frame_count: int


class ProfileOut(BaseModel):
    id: Optional[str] = None
    name: str
    age: str = ""
    status: str = ""
    image: Optional[str] = None
    enrolled_at: Optional[str] = None


class ProfileCreate(BaseModel):
    name: str
    age: str = ""
    status: str = "FRIEND"
    image_b64: Optional[str] = None
    # Optional list of base64 images for the device-camera 3-photo capture flow.
    # When present the first entry is treated as the primary image; the rest
    # generate additional embeddings to improve recognition accuracy.
    images: Optional[List[str]] = None
    allow_low_confidence: bool = False


class FrameCheckRequest(BaseModel):
    image_b64: str  # data-URL or raw base-64 JPEG


class FrameCheckOut(BaseModel):
    face_detected: bool
    face_count: int = 0
    lighting_ok: bool = False
    centered: bool = False
    message: str = ""


class SettingsPatch(BaseModel):
    settings: Dict[str, Any]
