"""
Recognition shim — delegates to vision.* (InsightFace + temporal).
"""

from collections import deque

import numpy as np

from vision import config as vcfg
from vision.aligner import ALIGN_SIZE, align_crop, align_from_landmarks, is_aligned
from vision.embedder import embed_bgr, embed_robust
from vision.matcher import (
    cosine_distance,
    cosine_similarity,
    is_embedding,
    l2_normalize,
    match_identity,
)
from vision.preprocess import padded_crop
from vision import temporal as tmp


def configure(settings: dict):
    vcfg.configure(settings)


def warmup_models():
    from vision.insightface_app import warmup

    warmup()


def is_aligned_crop(bgr_image) -> bool:
    return is_aligned(bgr_image)


def align_face(frame, x, y, w, h, kps=None):
    if kps is not None:
        return align_crop(frame, x, y, w, h, kps)
    crop = padded_crop(frame, x, y, w, h, pad_ratio=0.35)
    if crop.size == 0:
        return crop
    return crop


def extract_embedding(bgr_image, *, already_aligned=None, kps=None):
    if already_aligned is None:
        already_aligned = is_aligned_crop(bgr_image)
    if already_aligned:
        return embed_bgr(bgr_image, kps=None)
    return embed_bgr(bgr_image, kps=kps)


def extract_embeddings_robust(bgr_image, *, max_samples: int = 4, kps=None) -> list:
    return embed_robust(bgr_image, kps=kps, max_samples=max_samples)


def fuse_embedding_history(history: deque):
    return tmp.fuse_embedding_history(history)


def weighted_vote_name(vote_history: deque):
    return tmp.weighted_vote_name(vote_history)


def stability_percent(track: dict) -> int:
    return tmp.stability_percent(track)


def update_locked_identity(track: dict, candidate_name: str, candidate_score: float):
    tmp.update_locked_identity(track, candidate_name, candidate_score)


def apply_embedding_to_track(face_db: dict, track: dict, embedding):
    tmp.apply_embedding_to_track(face_db, track, embedding)


def recognize_track(face_db: dict, track: dict, bgr_crop, kps=None):
    from vision.matcher import sync_gallery
    if face_db:
        sync_gallery(face_db)
    embedding = extract_embedding(bgr_crop, already_aligned=is_aligned_crop(bgr_crop), kps=kps)
    apply_embedding_to_track(face_db, track, embedding)


def log_recognition(message: str):
    tmp._log(message)
