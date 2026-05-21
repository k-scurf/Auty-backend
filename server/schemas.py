"""API request/response models."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TrackOut(BaseModel):
    id: int
    bbox: List[int]
    name: str = "UNKNOWN"
    confidence: float = 0.0
    known: bool = False
    stability_pct: int = 0
    user_emotion: Optional[str] = None
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
    ready_to_save: bool = False
    preview_b64: Optional[str] = None
    auto_committed: bool = False
    provisional_name: Optional[str] = None


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


class SettingsPatch(BaseModel):
    settings: Dict[str, Any]
