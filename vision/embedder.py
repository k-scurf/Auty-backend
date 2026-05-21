"""ArcFace embedding extraction via InsightFace."""

from __future__ import annotations

import cv2
import numpy as np

from vision import insightface_app as ifa
from vision.aligner import ALIGN_SIZE, align_from_landmarks, is_aligned
from vision.matcher import l2_normalize


def _embed_via_recognition_model(bgr: np.ndarray) -> np.ndarray | None:
    """ArcFace forward on an already-aligned 112x112 crop (no detector)."""
    if bgr is None or bgr.size == 0:
        return None
    app = ifa.get_app()
    rec = app.models.get("recognition")
    if rec is None:
        return None
    h, w = bgr.shape[:2]
    target = rec.input_size
    if (w, h) != target:
        bgr = cv2.resize(bgr, target, interpolation=cv2.INTER_LINEAR)
    feat = rec.get_feat(bgr)
    if feat is None or feat.size == 0:
        return None
    return l2_normalize(feat.flatten())


def embed_bgr(bgr: np.ndarray, kps: np.ndarray | None = None) -> np.ndarray | None:
    """Return L2-normalized embedding."""
    if bgr is None or bgr.size == 0:
        return None

    if is_aligned(bgr):
        emb = _embed_via_recognition_model(bgr)
        if emb is not None:
            return emb
        faces = ifa.analyze(bgr)
        if faces and getattr(faces[0], "embedding", None) is not None:
            return l2_normalize(faces[0].embedding)
        return _embed_aligned_direct(bgr)

    if kps is not None:
        aligned = align_from_landmarks(bgr, kps)
        if aligned is not None and aligned.shape[:2] == (ALIGN_SIZE[1], ALIGN_SIZE[0]):
            return embed_bgr(aligned, kps=None)

    faces = ifa.analyze(bgr)
    if not faces:
        return None
    face = max(faces, key=lambda f: float(getattr(f, "det_score", 0)))
    if getattr(face, "embedding", None) is not None:
        return l2_normalize(face.embedding)
    if getattr(face, "kps", None) is not None:
        aligned = align_from_landmarks(bgr, face.kps)
        return _embed_aligned_direct(aligned)
    return None


def _embed_aligned_direct(aligned: np.ndarray) -> np.ndarray | None:
    emb = _embed_via_recognition_model(aligned)
    if emb is not None:
        return emb
    faces = ifa.analyze(aligned)
    if faces and getattr(faces[0], "embedding", None) is not None:
        return l2_normalize(faces[0].embedding)
    return None


def embed_robust(bgr: np.ndarray, kps: np.ndarray | None = None, max_samples: int = 4) -> list:
    out = []
    seen = set()

    def add(emb):
        if emb is None:
            return
        key = tuple(round(float(x), 4) for x in emb[:8])
        if key in seen:
            return
        seen.add(key)
        out.append(emb)

    add(embed_bgr(bgr, kps))
    if is_aligned(bgr):
        add(_embed_via_recognition_model(bgr))
    elif bgr.shape[0] >= 80 and bgr.shape[1] >= 80:
        up = cv2.resize(bgr, (224, 224), interpolation=cv2.INTER_LINEAR)
        add(embed_bgr(up, None))
    if kps is not None:
        from vision.aligner import align_from_landmarks

        aligned = align_from_landmarks(bgr, kps)
        add(embed_bgr(aligned, None))
    return out[:max_samples]
