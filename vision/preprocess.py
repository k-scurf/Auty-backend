"""Frame preprocessing — CLAHE and optional gamma."""

from __future__ import annotations

import cv2
import numpy as np

from vision.config import get_cfg


def padded_crop(frame, x, y, w, h, pad_ratio=0.30):
    pad_x = int(w * pad_ratio)
    pad_y = int(h * pad_ratio)
    frame_h, frame_w = frame.shape[:2]
    x1 = max(x - pad_x, 0)
    y1 = max(y - pad_y, 0)
    x2 = min(x + w + pad_x, frame_w)
    y2 = min(y + h + pad_y, frame_h)
    return frame[y1:y2, x1:x2]


def preprocess_frame(frame: np.ndarray) -> np.ndarray:
    if frame is None or frame.size == 0:
        return frame
    if not get_cfg("preprocess_clahe_enabled", True):
        return _apply_gamma(frame)
    return _clahe_l_channel(_apply_gamma(frame))


def preprocess_crop(crop: np.ndarray) -> np.ndarray:
    if crop is None or crop.size == 0:
        return crop
    if not get_cfg("preprocess_crop_clahe", False):
        return crop
    return _clahe_l_channel(crop)


def _apply_gamma(frame: np.ndarray) -> np.ndarray:
    gamma = float(get_cfg("preprocess_gamma", 1.0))
    if abs(gamma - 1.0) < 0.01:
        return frame
    inv = 1.0 / max(0.1, gamma)
    table = np.array(
        [((i / 255.0) ** inv) * 255 for i in range(256)], dtype=np.uint8
    )
    return cv2.LUT(frame, table)


def _clahe_l_channel(frame: np.ndarray) -> np.ndarray:
    clip = float(get_cfg("preprocess_clahe_clip_limit", 2.0))
    tile = int(get_cfg("preprocess_clahe_tile", 8))
    yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV)
    clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(tile, tile))
    yuv[:, :, 0] = clahe.apply(yuv[:, :, 0])
    return cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR)
