"""Face quality scoring and gating (adaptive by face size)."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from vision.config import get_cfg
from vision.verify_detection import landmarks_valid


@dataclass
class FaceQuality:
    passed: bool
    quality_score: float
    blur_score: float
    brightness: float
    area_ratio: float
    pose_yaw: float
    center_score: float
    reasons: list


def blur_variance(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _adaptive_blur_min(area_ratio: float) -> float:
    base = float(get_cfg("quality_min_blur_variance", 80))
    small_thresh = float(get_cfg("quality_small_face_area_ratio", 0.02))
    if area_ratio >= small_thresh:
        return base
    scale = max(0.5, area_ratio / small_thresh)
    return base / scale


def assess_face(
    frame,
    bbox,
    *,
    pose_yaw: float = 0.0,
    kps=None,
) -> FaceQuality:
    fh, fw = frame.shape[:2]
    x, y, w, h = bbox
    x, y = max(0, int(x)), max(0, int(y))
    w, h = max(1, min(int(w), fw - x)), max(1, min(int(h), fh - y))
    crop = frame[y : y + h, x : x + w]
    reasons = []

    if crop.size == 0:
        return FaceQuality(False, 0.0, 0.0, 0.0, 0.0, pose_yaw, 0.0, ["empty"])

    if kps is not None and not landmarks_valid(kps):
        return FaceQuality(False, 0.0, 0.0, 0.0, 0.0, pose_yaw, 0.0, ["landmarks"])

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    blur = blur_variance(gray)
    brightness = float(np.mean(gray))
    area_ratio = (w * h) / float(fw * fh)

    cx, cy = x + w * 0.5, y + h * 0.5
    dist = np.hypot(cx - fw * 0.5, cy - fh * 0.5)
    max_dist = np.hypot(fw * 0.5, fh * 0.5)
    center_score = max(0.0, 1.0 - dist / max_dist) * 100.0

    min_blur = _adaptive_blur_min(area_ratio)
    min_area = float(get_cfg("min_face_area_ratio", 0.006))
    max_area = float(get_cfg("max_face_area_ratio", 0.50))
    bright_lo = float(get_cfg("quality_brightness_low", 40))
    bright_hi = float(get_cfg("quality_brightness_high", 220))
    max_yaw = float(get_cfg("quality_max_yaw_deg", 35))

    subscores = []
    if min_blur <= 0 or blur >= min_blur:
        subscores.append(min(100.0, (blur / min_blur * 25) if min_blur > 0 else 25.0))
    else:
        reasons.append("blur")

    if min_area <= area_ratio <= max_area:
        subscores.append(25.0)
    else:
        reasons.append("size")

    if bright_lo <= brightness <= bright_hi:
        subscores.append(25.0)
    else:
        reasons.append("lighting")

    if abs(pose_yaw) <= max_yaw:
        subscores.append(25.0)
    else:
        reasons.append("pose")

    subscores.append(center_score * 0.25)
    quality_score = float(sum(subscores))
    passed = len(reasons) == 0 and quality_score >= float(
        get_cfg("quality_min_recognize", 50)
    )

    return FaceQuality(
        passed=passed,
        quality_score=round(quality_score, 1),
        blur_score=round(blur, 1),
        brightness=round(brightness, 1),
        area_ratio=round(area_ratio, 4),
        pose_yaw=round(pose_yaw, 1),
        center_score=round(center_score, 1),
        reasons=reasons,
    )


def passes_enroll(quality: FaceQuality) -> bool:
    return quality.quality_score >= float(get_cfg("quality_min_enroll", 65))


def passes_enroll_capture(quality: FaceQuality) -> bool:
    """Relaxed quality gate used only during guided enrollment capture."""
    min_score = float(get_cfg("quality_min_enroll_capture", 35))
    if quality.quality_score >= min_score:
        return True
    # One minor issue (e.g. slight off-center) is OK if overall score is close.
    if quality.quality_score >= min_score - 10 and len(quality.reasons) <= 1:
        return True
    return False
