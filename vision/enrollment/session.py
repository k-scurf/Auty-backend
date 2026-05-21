"""Guided enrollment FSM — configurable pose samples with partial auto-save."""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np

from vision.aligner import align_crop
from vision.config import get_cfg
from vision.embedder import embed_bgr
from vision.quality import assess_face, passes_enroll_capture

DEFAULT_PHASES = [
    ("front", "Look at the camera", 7, -12, 12),
    ("left", "Turn slightly to your left", 5, 8, 35),
    ("right", "Turn slightly to your right", 5, -35, -8),
    ("up", "Look up slightly", 4, -15, 15),
    ("down", "Look down slightly", 4, -15, 15),
]


def _min_auto() -> int:
    return int(get_cfg("enrollment_min_auto_save", 8))


def _min_ready() -> int:
    return int(get_cfg("enrollment_min_ready_ui", 6))


def _target_total() -> int:
    return int(get_cfg("enrollment_target_total", 25))


def _phase_timeout() -> float:
    return float(get_cfg("enrollment_phase_timeout_sec", 12))


@dataclass
class EnrollmentSession:
    active: bool = False
    track_id: Optional[int] = None
    phase_idx: int = 0
    samples: List[dict] = field(default_factory=list)
    rejected_blur: int = 0
    last_preview: Optional[np.ndarray] = None
    phase_started_at: float = 0.0

    def start(self, track_id: int):
        self.active = True
        self.track_id = track_id
        self.phase_idx = 0
        self.samples = []
        self.rejected_blur = 0
        self.last_preview = None
        self.phase_started_at = time.time()

    def cancel(self):
        self.active = False
        self.track_id = None
        self.phase_idx = 0
        self.samples = []
        self.rejected_blur = 0
        self.last_preview = None
        self.phase_started_at = 0.0

    def _phases(self):
        return DEFAULT_PHASES

    def _phase(self):
        phases = self._phases()
        if self.phase_idx >= len(phases):
            return None
        return phases[self.phase_idx]

    def _maybe_advance_phase_timeout(self):
        phase = self._phase()
        if phase is None:
            return
        name, _, target, _, _ = phase
        phase_n = len([s for s in self.samples if s["phase"] == name])
        if phase_n >= target:
            return
        if time.time() - self.phase_started_at >= _phase_timeout():
            self.phase_idx += 1
            self.phase_started_at = time.time()

    def _yaw_in_band(
        self, yaw: float, phase_name: str, yaw_min: float, yaw_max: float
    ) -> bool:
        relaxed = bool(get_cfg("enrollment_relaxed_pose", True))
        if relaxed:
            yaw_min -= 8
            yaw_max += 8
            if phase_name in ("left", "right"):
                if phase_name == "left":
                    yaw_min = max(0, yaw_min - 5)
                else:
                    yaw_max = min(0, yaw_max + 5)

        if phase_name == "front":
            return yaw_min <= yaw <= yaw_max
        if phase_name == "left":
            return yaw >= yaw_min
        if phase_name == "right":
            return yaw <= yaw_max
        return abs(yaw) <= (33 if relaxed else 25)

    def tick(
        self, frame, track: dict
    ) -> Tuple[bool, Optional[str]]:
        """Process one frame; returns (accepted_sample, reject_reason)."""
        if not self.active or track.get("id") != self.track_id:
            return False, None

        self._maybe_advance_phase_timeout()

        phase = self._phase()
        if phase is None:
            return False, None

        name, instruction, target, yaw_min, yaw_max = phase
        bbox = track.get("smooth_bbox") or track.get("bbox")
        if not bbox:
            return False, None

        x, y, w, h = bbox
        yaw = float(track.get("pose_yaw", 0))
        fq = assess_face(frame, bbox, pose_yaw=yaw)
        track["quality_score"] = fq.quality_score
        track["blur_score"] = fq.blur_score

        if not passes_enroll_capture(fq):
            if "blur" in fq.reasons:
                self.rejected_blur += 1
            return False, fq.reasons[0] if fq.reasons else "quality"

        if not self._yaw_in_band(yaw, name, yaw_min, yaw_max):
            return False, "pose"

        aligned = align_crop(frame, x, y, w, h, track.get("kps"))
        emb = embed_bgr(aligned, track.get("kps"))
        if emb is None:
            return False, "embed"

        phase_samples = [s for s in self.samples if s["phase"] == name]
        if len(phase_samples) >= target:
            self.phase_idx += 1
            self.phase_started_at = time.time()
            return False, None

        self.samples.append(
            {
                "phase": name,
                "embedding": emb,
                "crop": aligned.copy(),
                "pose": name,
            }
        )
        self.last_preview = aligned.copy()
        return True, None

    def _ready_to_save(self, captured: int) -> bool:
        return captured >= _min_auto()

    def progress(self) -> dict:
        min_auto = _min_auto()
        min_ready = _min_ready()
        total_target = _target_total()
        aspirational = sum(p[2] for p in self._phases())

        if not self.active:
            return {
                "active": False,
                "phase": "",
                "instruction": "",
                "captured": 0,
                "target": total_target,
                "min_auto": min_auto,
                "min_ready": min_ready,
                "percent": 0.0,
                "rejected_blur": self.rejected_blur,
                "ready_to_save": False,
                "preview_b64": None,
                "auto_committed": False,
                "provisional_name": None,
            }

        captured = len(self.samples)
        phase = self._phase()
        if phase is None:
            return {
                "active": True,
                "phase": "done",
                "instruction": "Ready — add a name (optional)",
                "captured": captured,
                "target": total_target,
                "min_auto": min_auto,
                "min_ready": min_ready,
                "percent": min(100.0, 100.0 * captured / max(1, min_auto)),
                "rejected_blur": self.rejected_blur,
                "ready_to_save": self._ready_to_save(captured),
                "preview_b64": self._preview_b64(),
                "auto_committed": False,
                "provisional_name": None,
            }

        name, instruction, target, _, _ = phase
        pct = min(100.0, 100.0 * captured / max(1, min_auto))

        return {
            "active": True,
            "phase": name,
            "instruction": instruction,
            "captured": captured,
            "target": total_target,
            "min_auto": min_auto,
            "min_ready": min_ready,
            "percent": round(pct, 1),
            "rejected_blur": self.rejected_blur,
            "ready_to_save": self._ready_to_save(captured),
            "preview_b64": self._preview_b64(),
            "auto_committed": False,
            "provisional_name": None,
        }

    def _preview_b64(self) -> Optional[str]:
        if self.last_preview is None:
            return None
        ok, buf = cv2.imencode(
            ".jpg", self.last_preview, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
        )
        if not ok:
            return None
        return base64.b64encode(buf).decode("ascii")

    def all_embeddings(self) -> List:
        return [s["embedding"] for s in self.samples]

    def all_crops(self) -> List[np.ndarray]:
        return [s["crop"] for s in self.samples]

    def poses(self) -> List[str]:
        return [s["pose"] for s in self.samples]
