"""Guided pose capture — yaw/pitch/roll estimation + stability-gated step sequence.

Drives the "Face ID style" auto-capture flow: estimate head pose from whatever
landmarks the pipeline already has (5-pt InsightFace kps, with an optional
MediaPipe FaceMesh upgrade path), hold the pose steady for N frames, then
signal the caller (vision/enrollment/session.py) that it's safe to capture.

This module owns pose math + the step state machine only. It does not touch
the camera, the embedder, or the identity store — callers feed it landmarks
per frame and read back a PoseGuideResult.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Sequence

import numpy as np

# ── Pose angles ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PoseAngles:
    yaw: float    # negative = subject turned to their left, positive = right
    pitch: float  # negative = looking up, positive = looking down
    roll: float   # negative = tilted left, positive = tilted right


def _angles_from_5pt(kps: np.ndarray) -> Optional[PoseAngles]:
    """Estimate yaw/pitch/roll from InsightFace's 5-point kps.

    Order: left_eye, right_eye, nose, left_mouth, right_mouth (subject's own
    left/right, matching vision/detector.py's convention).
    """
    if kps is None:
        return None
    pts = np.asarray(kps, dtype=np.float32).reshape(-1, 2)
    if pts.shape[0] < 5:
        return None

    left_eye, right_eye, nose, left_mouth, right_mouth = pts[:5]
    eye_mid = (left_eye + right_eye) * 0.5
    mouth_mid = (left_mouth + right_mouth) * 0.5
    interocular = float(np.linalg.norm(right_eye - left_eye))
    if interocular < 1e-3:
        return None

    # Yaw: horizontal nose offset from the eye midpoint, normalized by
    # interocular distance. Same convention as detector.estimate_pose_yaw.
    yaw = float(np.clip(((nose[0] - eye_mid[0]) / interocular) * 55.0, -45.0, 45.0))

    # Pitch: vertical position of the nose between the eye line and the
    # mouth line. At ~0.45-0.5 of the way down, pitch ~= 0 (looking ahead).
    face_height = float(np.linalg.norm(mouth_mid - eye_mid))
    if face_height < 1e-3:
        pitch = 0.0
    else:
        nose_t = (nose[1] - eye_mid[1]) / face_height  # 0 at eyes, 1 at mouth
        pitch = float(np.clip((nose_t - 0.48) * 90.0, -45.0, 45.0))

    # Roll: tilt of the eye line.
    roll = float(np.clip(
        np.degrees(np.arctan2(right_eye[1] - left_eye[1], right_eye[0] - left_eye[0])),
        -45.0, 45.0,
    ))

    return PoseAngles(yaw=yaw, pitch=pitch, roll=roll)


# Canonical 3D face model points (mm, arbitrary scale) for solvePnP, keyed by
# the MediaPipe FaceMesh landmark indices used to locate them in 2D.
_MEDIAPIPE_PNP_INDICES = [1, 152, 33, 263, 61, 291]  # nose tip, chin, eye outer corners, mouth corners
_MEDIAPIPE_MODEL_3D = np.array(
    [
        [0.0, 0.0, 0.0],        # nose tip
        [0.0, -63.6, -12.5],    # chin
        [-43.3, 32.7, -26.0],   # left eye outer corner
        [43.3, 32.7, -26.0],    # right eye outer corner
        [-28.9, -28.9, -24.1],  # mouth left corner
        [28.9, -28.9, -24.1],   # mouth right corner
    ],
    dtype=np.float64,
)


def _angles_from_facemesh(
    landmarks: np.ndarray, image_size: Sequence[int]
) -> Optional[PoseAngles]:
    """Upgrade path: solvePnP against MediaPipe's 468/478-point FaceMesh.

    `landmarks` is an (N, 2) or (N, 3) array of pixel-space (x, y[, z])
    coordinates. `image_size` is (width, height).
    """
    try:
        import cv2
    except ImportError:
        return None

    pts = np.asarray(landmarks, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] <= max(_MEDIAPIPE_PNP_INDICES):
        return None
    image_pts = pts[_MEDIAPIPE_PNP_INDICES, :2]

    w, h = image_size
    focal = float(w)
    camera_matrix = np.array(
        [[focal, 0, w / 2.0], [0, focal, h / 2.0], [0, 0, 1]], dtype=np.float64
    )
    dist_coeffs = np.zeros((4, 1))

    ok, rvec, _tvec = cv2.solvePnP(
        _MEDIAPIPE_MODEL_3D, image_pts, camera_matrix, dist_coeffs,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not ok:
        return None

    rot_mat, _ = cv2.Rodrigues(rvec)
    sy = float(np.sqrt(rot_mat[0, 0] ** 2 + rot_mat[1, 0] ** 2))
    singular = sy < 1e-6
    if not singular:
        pitch = np.degrees(np.arctan2(-rot_mat[2, 0], sy))
        yaw = np.degrees(np.arctan2(rot_mat[1, 0], rot_mat[0, 0]))
        roll = np.degrees(np.arctan2(rot_mat[2, 1], rot_mat[2, 2]))
    else:
        pitch = np.degrees(np.arctan2(-rot_mat[2, 0], sy))
        yaw = 0.0
        roll = 0.0

    return PoseAngles(
        yaw=float(np.clip(yaw, -90.0, 90.0)),
        pitch=float(np.clip(pitch, -90.0, 90.0)),
        roll=float(np.clip(roll, -90.0, 90.0)),
    )


def estimate_pose(
    kps: Optional[np.ndarray] = None,
    mesh_landmarks: Optional[np.ndarray] = None,
    image_size: Optional[Sequence[int]] = None,
) -> Optional[PoseAngles]:
    """Estimate head pose. Prefers FaceMesh (more accurate) when provided,
    otherwise falls back to the existing InsightFace 5-point kps."""
    if mesh_landmarks is not None and image_size is not None:
        angles = _angles_from_facemesh(mesh_landmarks, image_size)
        if angles is not None:
            return angles
    return _angles_from_5pt(kps)


# ── Pose sequence ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PoseTarget:
    name: str
    instruction: str
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    yaw_tolerance: float = 12.0
    pitch_tolerance: float = 12.0
    roll_tolerance: float = 15.0


DEFAULT_POSE_SEQUENCE: List[PoseTarget] = [
    PoseTarget("center", "Look straight ahead", yaw=0, pitch=0, roll=0),
    PoseTarget("left", "Turn slightly to your left", yaw=-22, pitch=0, roll=0),
    PoseTarget("right", "Turn slightly to your right", yaw=22, pitch=0, roll=0),
    PoseTarget("up", "Tilt your head up slightly", yaw=0, pitch=-18, roll=0),
    PoseTarget("down", "Tilt your head down slightly", yaw=0, pitch=18, roll=0),
]


@dataclass
class PoseGuideResult:
    step_index: int
    step_name: str
    instruction: str
    done: bool
    face_detected: bool
    angles: Optional[PoseAngles]
    delta_yaw: float = 0.0
    delta_pitch: float = 0.0
    delta_roll: float = 0.0
    in_band: bool = False
    stability_progress: float = 0.0  # 0..1
    ready_to_capture: bool = False
    completed_steps: List[str] = field(default_factory=list)


class PoseGuide:
    """Stateful, per-track pose-guidance FSM with a stability buffer.

    Runs on the backend (per the recognition worker's per-frame tick), fed by
    whatever detector already produced kps/landmarks for the tracked face.
    """

    def __init__(
        self,
        sequence: Optional[Sequence[PoseTarget]] = None,
        stability_frames: int = 8,
    ):
        self.sequence: List[PoseTarget] = list(sequence or DEFAULT_POSE_SEQUENCE)
        self.stability_frames = max(1, int(stability_frames))
        self.step_idx = 0
        self.completed_steps: List[str] = []
        self._buffer: Deque[bool] = deque(maxlen=self.stability_frames)

    def reset(self) -> None:
        self.step_idx = 0
        self.completed_steps = []
        self._buffer.clear()

    @property
    def is_complete(self) -> bool:
        return self.step_idx >= len(self.sequence)

    def current_target(self) -> Optional[PoseTarget]:
        if self.is_complete:
            return None
        return self.sequence[self.step_idx]

    def update(
        self,
        kps: Optional[np.ndarray] = None,
        mesh_landmarks: Optional[np.ndarray] = None,
        image_size: Optional[Sequence[int]] = None,
    ) -> PoseGuideResult:
        """Feed one frame's landmarks. Does not advance the step — call
        confirm_capture() once the caller has actually captured a sample."""
        target = self.current_target()
        if target is None:
            return PoseGuideResult(
                step_index=self.step_idx,
                step_name="done",
                instruction="All poses captured",
                done=True,
                face_detected=True,
                angles=None,
                completed_steps=list(self.completed_steps),
            )

        angles = estimate_pose(kps, mesh_landmarks, image_size)
        if angles is None:
            self._buffer.clear()
            return PoseGuideResult(
                step_index=self.step_idx,
                step_name=target.name,
                instruction=target.instruction,
                done=False,
                face_detected=False,
                angles=None,
                completed_steps=list(self.completed_steps),
            )

        d_yaw = angles.yaw - target.yaw
        d_pitch = angles.pitch - target.pitch
        d_roll = angles.roll - target.roll
        in_band = (
            abs(d_yaw) <= target.yaw_tolerance
            and abs(d_pitch) <= target.pitch_tolerance
            and abs(d_roll) <= target.roll_tolerance
        )

        if in_band:
            self._buffer.append(True)
        else:
            self._buffer.clear()

        progress = len(self._buffer) / self.stability_frames
        ready = in_band and len(self._buffer) >= self.stability_frames

        return PoseGuideResult(
            step_index=self.step_idx,
            step_name=target.name,
            instruction=target.instruction,
            done=False,
            face_detected=True,
            angles=angles,
            delta_yaw=d_yaw,
            delta_pitch=d_pitch,
            delta_roll=d_roll,
            in_band=in_band,
            stability_progress=min(1.0, progress),
            ready_to_capture=ready,
            completed_steps=list(self.completed_steps),
        )

    def clear_buffer(self) -> None:
        """Drop accumulated stability progress without advancing the step —
        used when the face drops out of frame mid-hold."""
        self._buffer.clear()

    def status(self) -> dict:
        """Last-known stability state without consuming a new frame — safe to
        call from a status/progress endpoint between ticks."""
        target = self.current_target()
        progress = len(self._buffer) / self.stability_frames
        ready = bool(self._buffer) and len(self._buffer) >= self.stability_frames
        return {
            "pose_target": target.name if target else None,
            "stability_progress": round(min(1.0, progress), 3),
            "ready_to_capture": ready,
        }

    def confirm_capture(self) -> None:
        """Caller calls this after it has captured+accepted a sample for the
        current step. Advances to the next pose and clears the buffer."""
        target = self.current_target()
        if target is None:
            return
        self.completed_steps.append(target.name)
        self.step_idx += 1
        self._buffer.clear()
