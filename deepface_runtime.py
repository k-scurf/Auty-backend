"""
Thread-safe DeepFace access (TensorFlow models are not thread-safe).
Shared by face_detection (RetinaFace) and recognition (ArcFace).
"""

from __future__ import annotations

import os

# Keras 3 / TF 2.16+ compatibility for RetinaFace and ArcFace stacks.
os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import threading
from typing import Any, List, Optional

import cv2
import numpy as np

_lock = threading.Lock()
_deepface = None
_warmed = False
_models_ready = threading.Event()


def get_deepface():
    global _deepface
    if _deepface is None:
        from deepface import DeepFace

        _deepface = DeepFace
    return _deepface


def models_ready() -> bool:
    return _models_ready.is_set()


def extract_faces(
    img,
    *,
    detector_backend: str = "retinaface",
    enforce_detection: bool = False,
    align: bool = False,
    **kwargs: Any,
) -> List[dict]:
    if not _models_ready.is_set():
        return []
    if not _lock.acquire(blocking=False):
        return []
    try:
        return get_deepface().extract_faces(
            img_path=img,
            detector_backend=detector_backend,
            enforce_detection=enforce_detection,
            align=align,
            **kwargs,
        )
    finally:
        _lock.release()


def represent(
    img,
    *,
    model_name: str = "ArcFace",
    detector_backend: str = "retinaface",
    enforce_detection: bool = False,
    align: bool = True,
    **kwargs: Any,
) -> List[dict]:
    if not _models_ready.is_set():
        return []
    with _lock:
        return get_deepface().represent(
            img_path=img,
            model_name=model_name,
            detector_backend=detector_backend,
            enforce_detection=enforce_detection,
            align=align,
            **kwargs,
        )


def face_array_to_bgr_uint8(face) -> Optional[np.ndarray]:
    """Normalize DeepFace face tensors to BGR uint8."""
    if face is None:
        return None
    arr = np.asarray(face)
    if arr.size == 0:
        return None
    if arr.dtype != np.uint8:
        if arr.max() <= 1.0:
            arr = (arr * 255.0).clip(0, 255).astype(np.uint8)
        else:
            arr = arr.clip(0, 255).astype(np.uint8)
    if arr.ndim == 3 and arr.shape[2] == 3:
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    return arr


def warmup(
    *,
    model_name: str = "ArcFace",
    detector_backend: str = "retinaface",
) -> None:
    """Pre-load ArcFace + probe detector (first run may download weights)."""
    global _warmed
    dummy = np.zeros((112, 112, 3), dtype=np.uint8)
    try:
        with _lock:
            get_deepface().represent(
                img_path=dummy,
                model_name=model_name,
                detector_backend="skip",
                enforce_detection=False,
                align=False,
            )
        _warmed = True
        print(f"[Auty] DeepFace ready: {model_name} (embeddings)")
        # Probe RetinaFace without blocking the live loop later.
        try:
            with _lock:
                get_deepface().extract_faces(
                    img_path=dummy,
                    detector_backend=detector_backend,
                    enforce_detection=False,
                    align=False,
                )
            print(f"[Auty] Detector ready: {detector_backend}")
        except Exception as exc:
            print(f"[Auty] {detector_backend} unavailable ({exc}); will use fallback detector.")
            import face_detection as fd

            fd.mark_deepface_detector_failed(detector_backend)
    except Exception as exc:
        print(f"[Auty] DeepFace warmup failed: {exc}")
    finally:
        _models_ready.set()
