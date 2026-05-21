"""Strict post-filters for face detections — reduce false boxes."""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from vision.config import get_cfg


def nms_boxes(boxes: List[Tuple[int, int, int, int]], scores: List[float], iou_thresh: float):
    if not boxes:
        return []
    areas = [w * h for (_, _, w, h) in boxes]
    order = sorted(range(len(boxes)), key=lambda i: areas[i], reverse=True)
    keep = []
    while order:
        i = order.pop(0)
        keep.append(i)
        remaining = []
        for j in order:
            if _iou(boxes[i], boxes[j]) < iou_thresh:
                remaining.append(j)
        order = remaining
    return keep


def _iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter == 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def landmarks_valid(kps: np.ndarray) -> bool:
    if kps is None:
        return False
    kps = np.asarray(kps, dtype=np.float32).reshape(-1, 2)
    if kps.shape[0] < 5 or not np.isfinite(kps).all():
        return False
    left_eye, right_eye, nose = kps[0], kps[1], kps[2]
    mouth_l, mouth_r = kps[3], kps[4]

    if right_eye[0] <= left_eye[0]:
        return False
    interocular = float(np.linalg.norm(right_eye - left_eye))
    if interocular < 1e-3:
        return False

    eye_y = (left_eye[1] + right_eye[1]) * 0.5
    if nose[1] <= eye_y:
        return False
    mouth_y = (mouth_l[1] + mouth_r[1]) * 0.5
    if mouth_y <= nose[1]:
        return False

    eye_mid_x = (left_eye[0] + right_eye[0]) * 0.5
    if abs(nose[0] - eye_mid_x) > interocular * 0.85:
        return False

    return True


def landmark_geometry_ok(bbox: Tuple[int, int, int, int], kps: np.ndarray) -> bool:
    if not landmarks_valid(kps):
        return False
    x, y, w, h = bbox
    if w < 1 or h < 1:
        return False
    kps = np.asarray(kps, dtype=np.float32).reshape(-1, 2)
    left_eye, right_eye = kps[0], kps[1]
    interocular = float(np.linalg.norm(right_eye - left_eye))
    ratio = interocular / float(w)
    min_ratio = float(get_cfg("landmark_min_interocular_ratio", 0.18))
    max_ratio = float(get_cfg("landmark_max_interocular_ratio", 0.55))
    return min_ratio <= ratio <= max_ratio


def min_det_score() -> float:
    mode = str(get_cfg("detection_mode", "balanced")).lower()
    if mode == "strict":
        return float(get_cfg("det_min_score_strict", 0.65))
    return float(get_cfg("insightface_det_thresh", 0.5))


def verify_candidate(bbox, score: float, kps: np.ndarray) -> bool:
    if score < min_det_score():
        return False
    if not landmark_geometry_ok(bbox, kps):
        return False
    return True


def filter_detections(candidates: list) -> list:
    """Filter list of objects with .bbox, .score, .kps attributes."""
    if not candidates:
        return []

    passed = [c for c in candidates if verify_candidate(c.bbox, c.score, c.kps)]
    if not passed:
        return []

    boxes = [c.bbox for c in passed]
    scores = [c.score for c in passed]
    iou = float(get_cfg("det_nms_iou", 0.4))
    keep_idx = nms_boxes(boxes, scores, iou)
    return [passed[i] for i in keep_idx]
