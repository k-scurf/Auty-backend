"""Cosine matching against identity gallery with strict accept rules."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from vision.config import get_cfg
from vision.gallery import GalleryIndex, get_gallery, rebuild_from_face_db


@dataclass
class MatchResult:
    name: str
    best_score: float
    second_score: float
    distance: float
    margin: float
    accepted: bool
    reject_reason: str = ""


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


def cosine_similarity(a, b) -> float:
    va = np.asarray(a, dtype=np.float32).flatten()
    vb = np.asarray(b, dtype=np.float32).flatten()
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom < 1e-9:
        return -1.0
    return float(np.dot(va, vb) / denom)


def cosine_distance(a, b) -> float:
    return 1.0 - cosine_similarity(a, b)


def sync_gallery(face_db: Dict[str, List], store=None) -> None:
    if store is not None and getattr(store, "_records", None):
        from vision.gallery import rebuild_from_store

        rebuild_from_store(store._records.values())
    else:
        rebuild_from_face_db(face_db)


def match_identity_detailed(
    embedding,
    *,
    gallery: GalleryIndex | None = None,
    locked_name: str | None = None,
) -> MatchResult:
    if embedding is None:
        return MatchResult("UNKNOWN", -1.0, -1.0, -1.0, 0.0, False, "no_embedding")

    gal = gallery or get_gallery()
    if gal.size == 0:
        return MatchResult("UNKNOWN", -1.0, -1.0, -1.0, 0.0, False, "empty_gallery")

    query = np.asarray(l2_normalize(embedding), dtype=np.float32)
    person_scores: List[float] = []
    for i, name in enumerate(gal.names):
        mat = (
            gal.samples[i]
            if i < len(gal.samples) and gal.samples[i] is not None and gal.samples[i].size
            else gal.masters[i : i + 1]
        )
        if mat.ndim == 1:
            mat = mat.reshape(1, -1)
        person_scores.append(float(np.max(mat @ query)))

    scores_arr = np.asarray(person_scores, dtype=np.float32)
    order = np.argsort(scores_arr)[::-1]
    best_i = int(order[0])
    best_score = float(scores_arr[best_i])
    second_score = float(scores_arr[int(order[1])]) if len(order) > 1 else -1.0
    margin = best_score - second_score
    best_name = gal.names[best_i]

    retain_th = float(get_cfg("lock_retain_threshold", 0.40))
    release_th = float(get_cfg("lock_release_threshold", 0.32))
    global_th = float(get_cfg("confidence_threshold", 0.48))
    min_margin = float(get_cfg("score_margin", 0.06))
    person_th = gal.thresholds.get(best_name, global_th)

    if locked_name and locked_name != "UNKNOWN" and locked_name == best_name:
        if best_score >= retain_th:
            mat = (
                gal.samples[best_i]
                if best_i < len(gal.samples) and gal.samples[best_i].size
                else gal.masters[best_i : best_i + 1]
            )
            if mat.ndim == 1:
                mat = mat.reshape(1, -1)
            dists = [1.0 - float(s) for s in mat @ query]
            return MatchResult(
                best_name,
                best_score,
                second_score,
                dists[0] if dists else 1.0 - best_score,
                margin,
                True,
                "retain_lock",
            )
        if best_score >= release_th:
            return MatchResult(
                locked_name,
                best_score,
                second_score,
                1.0 - best_score,
                margin,
                True,
                "weak_retain",
            )

    if best_score < person_th:
        return MatchResult(
            "UNKNOWN",
            best_score,
            second_score,
            max(0.0, 1.0 - best_score),
            margin,
            False,
            "below_threshold",
        )
    if margin < min_margin:
        return MatchResult(
            "UNKNOWN",
            best_score,
            second_score,
            max(0.0, 1.0 - best_score),
            margin,
            False,
            "low_margin",
        )

    dist = 1.0 - best_score
    return MatchResult(
        best_name,
        best_score,
        second_score,
        dist,
        margin,
        True,
        "accepted",
    )


def match_identity(
    face_db: Dict[str, List], embedding, *, locked_name: str | None = None
) -> Tuple[str, float, float, float]:
    if face_db and get_gallery().size == 0:
        sync_gallery(face_db)
    result = match_identity_detailed(embedding, locked_name=locked_name)
    name = result.name if result.accepted else "UNKNOWN"
    if get_cfg("debug_scores", False):
        _log(
            f"match name={result.name} accepted={result.accepted} "
            f"score={result.best_score:.3f} margin={result.margin:.3f} "
            f"reason={result.reject_reason}"
        )
    return name, result.best_score, result.second_score, result.distance


def is_true_unknown(result: MatchResult) -> bool:
    """True unknown — not a near-miss against gallery (suppress false unknown alerts)."""
    alert_max = float(get_cfg("unknown_alert_max", 0.35))
    if result.accepted:
        return False
    return result.best_score < alert_max


def _log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    path = get_cfg("log_file", "logs.txt")
    try:
        with open(path, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass
