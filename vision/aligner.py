"""ArcFace 5-point alignment to 112x112."""

from __future__ import annotations

import cv2
import numpy as np

ALIGN_SIZE = (112, 112)

_DST_5PT = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


def align_from_landmarks(bgr: np.ndarray, kps: np.ndarray) -> np.ndarray:
    """Warp face using 5 landmarks (eyes, nose, mouth corners)."""
    if bgr is None or bgr.size == 0 or kps is None:
        return bgr
    src = np.asarray(kps, dtype=np.float32).reshape(5, 2)
    matrix, _ = cv2.estimateAffinePartial2D(src, _DST_5PT, method=cv2.LMEDS)
    if matrix is None:
        return bgr
    return cv2.warpAffine(bgr, matrix, ALIGN_SIZE, borderMode=cv2.BORDER_REFLECT)


def align_crop(frame: np.ndarray, x: int, y: int, w: int, h: int, kps: np.ndarray | None) -> np.ndarray:
    from vision.preprocess import padded_crop

    pad_x = int(w * 0.30)
    pad_y = int(h * 0.30)
    x1 = max(x - pad_x, 0)
    y1 = max(y - pad_y, 0)
    crop = padded_crop(frame, x, y, w, h)
    if crop.size == 0:
        return crop
    if kps is not None and len(kps) >= 5:
        local = np.asarray(kps, dtype=np.float32).copy()
        local[:, 0] -= x1
        local[:, 1] -= y1
        return align_from_landmarks(crop, local)
    return crop


def is_aligned(bgr: np.ndarray) -> bool:
    if bgr is None or bgr.size == 0:
        return False
    h, w = bgr.shape[:2]
    return h == ALIGN_SIZE[1] and w == ALIGN_SIZE[0]
