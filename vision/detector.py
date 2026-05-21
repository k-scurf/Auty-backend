"""RetinaFace detection via InsightFace with strict verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import cv2
import numpy as np

from vision import insightface_app as ifa
from vision.config import get_cfg
from vision.verify_detection import filter_detections


@dataclass
class FaceDetection:
    bbox: Tuple[int, int, int, int]
    score: float
    kps: np.ndarray
    pose_yaw: float = 0.0
    pose_pitch: float = 0.0


def _bbox_xywh(x1, y1, x2, y2, fw: int, fh: int) -> Tuple[int, int, int, int]:
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(fw, int(x2)), min(fh, int(y2))
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    return x1, y1, w, h


def estimate_pose_yaw(kps: np.ndarray) -> float:
    if kps is None or len(kps) < 3:
        return 0.0
    kps = np.asarray(kps).reshape(-1, 2)
    left_eye, right_eye, nose = kps[0], kps[1], kps[2]
    eye_mid = (left_eye + right_eye) * 0.5
    interocular = np.linalg.norm(right_eye - left_eye)
    if interocular < 1e-3:
        return 0.0
    offset = (nose[0] - eye_mid[0]) / interocular
    return float(np.clip(offset * 55.0, -45.0, 45.0))


def _detect_scale() -> float:
    if bool(get_cfg("detect_performance_mode", False)):
        return float(get_cfg("retinaface_detect_scale", 0.75))
    if bool(get_cfg("detect_full_resolution", True)):
        return 1.0
    return float(get_cfg("retinaface_detect_scale", 1.0))


def detect(frame: np.ndarray, *, max_faces: int | None = None) -> List[FaceDetection]:
    if frame is None or frame.size == 0:
        return []

    scale = max(0.35, min(1.0, _detect_scale()))
    fh, fw = frame.shape[:2]
    if scale < 0.999:
        small = cv2.resize(
            frame,
            (max(320, int(fw * scale)), max(240, int(fh * scale))),
            interpolation=cv2.INTER_LINEAR,
        )
        inv = fw / float(small.shape[1])
    else:
        small = frame
        inv = 1.0

    cap = max_faces or int(get_cfg("max_face_detections", 4))
    try:
        raw_faces = ifa.detect_faces(small, max_num=cap)
    except Exception as exc:
        print(f"[vision] detect failed: {exc}")
        return []

    candidates: List[FaceDetection] = []
    for face in raw_faces:
        score = float(getattr(face, "det_score", 0))
        x1, y1, x2, y2 = face.bbox
        x1, y1, x2, y2 = x1 * inv, y1 * inv, x2 * inv, y2 * inv
        bbox = _bbox_xywh(x1, y1, x2, y2, fw, fh)
        kps = getattr(face, "kps", None)
        if kps is None:
            continue
        kps = np.asarray(kps, dtype=np.float32) * inv
        yaw = estimate_pose_yaw(kps)
        candidates.append(
            FaceDetection(bbox=bbox, score=score, kps=kps, pose_yaw=yaw)
        )

    verified = filter_detections(candidates)
    verified.sort(key=lambda d: d.bbox[2] * d.bbox[3], reverse=True)
    return verified[:cap]
