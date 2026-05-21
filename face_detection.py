"""
Face detection — InsightFace (default) with Haar fallback.
"""

from __future__ import annotations

from typing import List, Optional, Tuple, Union

import cv2
import numpy as np

from vision.detector import detect as insightface_detect

_mp_face_detection = None
try:
    import mediapipe as mp

    _mp_face_detection = mp.solutions.face_detection.FaceDetection(
        model_selection=0,
        min_detection_confidence=0.65,
    )
except Exception:
    _mp_face_detection = None


def create_haar_cascade():
    return cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )


def bbox_iou(box_a, box_b) -> float:
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter == 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def nms_detections(detections, iou_threshold=0.4):
    if len(detections) == 0:
        return []
    boxes = [tuple(int(v) for v in d) for d in detections]
    areas = [w * h for (_, _, w, h) in boxes]
    order = sorted(range(len(boxes)), key=lambda i: areas[i], reverse=True)
    keep = []
    while order:
        i = order.pop(0)
        keep.append(boxes[i])
        order = [j for j in order if bbox_iou(boxes[i], boxes[j]) < iou_threshold]
    return keep


def _clamp_bbox(bbox, frame_w, frame_h):
    x, y, w, h = bbox
    x = max(0, min(int(x), frame_w - 1))
    y = max(0, min(int(y), frame_h - 1))
    w = max(1, min(int(w), frame_w - x))
    h = max(1, min(int(h), frame_h - y))
    return (x, y, w, h)


def validate_face_region(frame, bbox, settings, *, strict=False) -> bool:
    fh, fw = frame.shape[:2]
    bbox = _clamp_bbox(bbox, fw, fh)
    x, y, w, h = bbox

    min_w = int(settings.get("min_face_width", 50))
    min_h = int(settings.get("min_face_height", 50))
    if w < min_w or h < min_h:
        return False

    area_ratio = (w * h) / float(fw * fh)
    if area_ratio < float(settings.get("min_face_area_ratio", 0.008)):
        return False
    if area_ratio > float(settings.get("max_face_area_ratio", 0.50)):
        return False

    aspect = w / float(h)
    if aspect < float(settings.get("min_aspect_ratio", 0.65)):
        return False
    if aspect > float(settings.get("max_aspect_ratio", 1.45)):
        return False

    if not strict:
        return True

    crop = frame[y : y + h, x : x + w]
    if crop.size == 0:
        return False

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if cv2.Laplacian(gray, cv2.CV_64F).var() < float(
        settings.get("min_laplacian_var", 25.0)
    ):
        return False

    if settings.get("use_skin_filter", False):
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([0, 20, 40]), np.array([30, 200, 255]))
        if float(np.count_nonzero(mask)) / mask.size < float(
            settings.get("min_skin_ratio", 0.04)
        ):
            return False

    if settings.get("use_mediapipe_verify", False) and _mp_face_detection is not None:
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        if not _mp_face_detection.process(rgb).detections:
            return False

    return True


def detect_faces_haar(frame, cascade, settings) -> list:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    min_size = int(settings.get("haar_min_size", 60))
    raw = cascade.detectMultiScale(
        gray,
        scaleFactor=float(settings.get("haar_scale_factor", 1.1)),
        minNeighbors=int(settings.get("haar_min_neighbors", 6)),
        minSize=(min_size, min_size),
        flags=cv2.CASCADE_SCALE_IMAGE,
    )
    merged = nms_detections(
        raw, iou_threshold=float(settings.get("nms_iou_threshold", 0.4))
    )
    use_strict = bool(settings.get("use_strict_detection_filter", False))
    return [
        {"bbox": b, "kps": None, "pose_yaw": 0.0}
        for b in merged
        if validate_face_region(frame, b, settings, strict=use_strict)
    ]


def detect_faces_insightface(frame, settings) -> list:
    max_det = int(settings.get("max_face_detections", 3))
    dets = insightface_detect(frame, max_faces=max_det)
    use_strict = bool(settings.get("use_strict_detection_filter", True))
    out = []
    for d in dets:
        if validate_face_region(frame, d.bbox, settings, strict=use_strict):
            out.append(
                {"bbox": d.bbox, "kps": d.kps, "pose_yaw": d.pose_yaw, "score": d.score}
            )
    return out


def detect_faces(frame, cascade, settings) -> list:
    """
    Returns list of dicts: bbox, kps, pose_yaw (InsightFace) or Haar fallback.
    """
    mode = str(settings.get("face_detector", "insightface")).lower()
    if mode == "haar":
        return detect_faces_haar(frame, cascade, settings)

    boxes = detect_faces_insightface(frame, settings)
    if boxes:
        return boxes
    strict = str(settings.get("detection_mode", "balanced")).lower() == "strict"
    if strict:
        return []
    if bool(settings.get("haar_fallback_on_retinaface_fail", True)):
        return detect_faces_haar(frame, cascade, settings)
    return []


def detect_faces_legacy_boxes(frame, cascade, settings) -> list:
    """Tuple bboxes only — for callers expecting old format."""
    return [d["bbox"] for d in detect_faces(frame, cascade, settings)]
