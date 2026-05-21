"""Precomputed identity gallery for fast matrix matching."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from vision.config import get_cfg


def l2_normalize(embedding) -> list:
    arr = np.asarray(embedding, dtype=np.float32).flatten()
    norm = np.linalg.norm(arr)
    if norm < 1e-9:
        return arr.tolist()
    return (arr / norm).tolist()


def is_embedding(value) -> bool:
    try:
        arr = np.asarray(value, dtype=np.float32)
    except (TypeError, ValueError):
        return False
    return arr.ndim == 1 and arr.size > 0 and np.isfinite(arr).all()


@dataclass
class GalleryIndex:
    names: List[str]
    masters: np.ndarray
    thresholds: Dict[str, float]
    samples: List[np.ndarray] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.names)


_gallery: Optional[GalleryIndex] = None


def _person_threshold(
    cal: dict, global_th: float, buffer: float, n_samples: int
) -> float:
    personal = cal.get("enroll_score_min")
    min_auto = int(get_cfg("enrollment_min_auto_save", 8))
    if personal is not None:
        th = max(global_th, float(personal) - buffer)
        if n_samples < min_auto or cal.get("sparse_enroll"):
            th = max(th, global_th + 0.02)
        return th
    return global_th


def rebuild_from_store(records) -> GalleryIndex:
    global _gallery
    names = []
    masters = []
    sample_mats = []
    thresholds = {}
    global_th = float(get_cfg("confidence_threshold", 0.48))
    buffer = float(get_cfg("enroll_threshold_buffer", 0.08))

    for rec in records:
        normed = [l2_normalize(e) for e in rec.embeddings if is_embedding(e)]
        if not normed:
            emb = rec.master_embedding
            if is_embedding(emb):
                normed = [l2_normalize(emb)]
        if not normed:
            continue

        master = l2_normalize(
            rec.master_embedding
            if is_embedding(rec.master_embedding)
            else np.mean(np.array(normed), axis=0)
        )
        names.append(rec.name)
        masters.append(master)
        sample_mats.append(np.array(normed, dtype=np.float32))
        cal = (rec.metadata or {}).get("calibration", {})
        thresholds[rec.name] = _person_threshold(
            cal, global_th, buffer, len(normed)
        )

    if names:
        mat = np.array(masters, dtype=np.float32)
    else:
        mat = np.zeros((0, 512), dtype=np.float32)

    _gallery = GalleryIndex(
        names=names, masters=mat, thresholds=thresholds, samples=sample_mats
    )
    return _gallery


def rebuild_from_face_db(face_db: Dict[str, List]) -> GalleryIndex:
    """Fallback when only name -> embeddings dict is available."""
    global _gallery
    names = []
    masters = []
    sample_mats = []
    global_th = float(get_cfg("confidence_threshold", 0.48))

    for name, samples in face_db.items():
        normed = [l2_normalize(s) for s in samples if is_embedding(s)]
        if not normed:
            continue
        master = l2_normalize(np.mean(np.array(normed), axis=0))
        names.append(name)
        masters.append(master)
        sample_mats.append(np.array(normed, dtype=np.float32))

    mat = (
        np.array(masters, dtype=np.float32)
        if names
        else np.zeros((0, 512), dtype=np.float32)
    )
    _gallery = GalleryIndex(
        names=names,
        masters=mat,
        thresholds={n: global_th for n in names},
        samples=sample_mats,
    )
    return _gallery


def get_gallery() -> GalleryIndex:
    if _gallery is None:
        return GalleryIndex(
            [], np.zeros((0, 512), dtype=np.float32), {}, []
        )
    return _gallery
