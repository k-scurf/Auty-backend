"""Thread-safe InsightFace FaceAnalysis singleton."""

from __future__ import annotations

import threading
from typing import List, Optional

import numpy as np

_lock = threading.Lock()
_app = None
_ready = threading.Event()
_init_error: Optional[str] = None


def get_app():
    global _app, _init_error
    if _app is not None:
        return _app
    with _lock:
        if _app is not None:
            return _app
        try:
            from insightface.app import FaceAnalysis

            from vision.config import get_cfg

            pack = str(_pack_name())
            providers = _onnx_providers()
            _app = FaceAnalysis(name=pack, providers=providers)
            det_size = int(_det_size())
            det_thresh = float(get_cfg("insightface_det_thresh", 0.5))
            _app.prepare(
                ctx_id=-1,
                det_size=(det_size, det_size),
                det_thresh=det_thresh,
            )
            print(
                f"[vision] InsightFace ready: {pack} det_size={det_size} "
                f"det_thresh={det_thresh}"
            )
        except Exception as exc:
            _init_error = str(exc)
            raise
    return _app


def _pack_name() -> str:
    from vision.config import get_cfg

    return get_cfg("insightface_pack", "buffalo_l")


def _det_size() -> int:
    from vision.config import get_cfg

    return int(get_cfg("insightface_det_size", 640))


def _onnx_providers():
    from vision.config import get_cfg

    use_gpu = bool(get_cfg("insightface_use_gpu", False))
    if use_gpu:
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def models_ready() -> bool:
    return _ready.is_set()


def warmup() -> None:
    """Load models once before the live loop."""
    global _init_error
    if _ready.is_set():
        return
    try:
        app = get_app()
        _ready.set()
        dummy = np.zeros((112, 112, 3), dtype=np.uint8)
        with _lock:
            app.det_model.detect(dummy, max_num=1, metric="default")
    except Exception as exc:
        _init_error = str(exc)
        print(f"[vision] InsightFace warmup failed: {exc}")
        _ready.set()


def detect_faces(bgr_image: np.ndarray, *, max_num: int = 0) -> List:
    """Detection only (no per-face recognition) — for strict filtering pipeline."""
    if not _ready.is_set():
        warmup()
    app = get_app()
    with _lock:
        bboxes, kpss = app.det_model.detect(bgr_image, max_num=max_num, metric="default")
    if bboxes is None or bboxes.shape[0] == 0:
        return []

    from insightface.app.common import Face

    faces = []
    for i in range(bboxes.shape[0]):
        bbox = bboxes[i, 0:4]
        det_score = float(bboxes[i, 4])
        kps = kpss[i] if kpss is not None else None
        face = Face(bbox=bbox, kps=kps, det_score=det_score)
        faces.append(face)
    return faces


def analyze(bgr_image: np.ndarray, *, max_num: int = 0):
    """Full detect + attribute models (used for embedding on crops)."""
    if not _ready.is_set():
        warmup()
    with _lock:
        return get_app().get(bgr_image, max_num=max_num)
