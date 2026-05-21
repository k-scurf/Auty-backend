"""Temporal fusion, voting, and hysteresis identity lock."""

from __future__ import annotations

import time
from collections import Counter, deque

import numpy as np

from vision.config import get_cfg
from vision.matcher import (
    MatchResult,
    match_identity_detailed,
    sync_gallery,
)


def fuse_embedding_history(history: deque):
    if not history:
        return None
    from vision.matcher import l2_normalize

    stack = np.array(list(history), dtype=np.float32)
    return l2_normalize(np.mean(stack, axis=0))


def weighted_vote_name(vote_history: deque):
    min_frames = int(get_cfg("vote_min_frames", 6))
    min_ratio = float(get_cfg("min_vote_ratio", 0.65))
    min_vote_score = float(get_cfg("min_vote_score", 0.35))

    if len(vote_history) < min_frames:
        return "UNKNOWN", 0.0, 0.0

    weighted = {}
    counts = Counter()
    total = len(vote_history)
    for name, score, _ts in vote_history:
        if name == "UNKNOWN":
            if score is None or score < min_vote_score:
                continue
            counts["UNKNOWN"] += 1
            continue
        if score is None or score < min_vote_score:
            continue
        counts[name] += 1
        weighted[name] = weighted.get(name, 0.0) + score

    if not weighted:
        return "UNKNOWN", 0.0, counts.get("UNKNOWN", 0) / max(1, total)

    name = max(weighted, key=weighted.get)
    ratio = counts[name] / total
    avg_score = weighted[name] / counts[name]

    if ratio < min_ratio:
        return "UNKNOWN", avg_score, ratio

    return name, avg_score, ratio


def stability_percent(track: dict) -> int:
    votes = track.get("vote_history")
    locked = track.get("locked_name", "UNKNOWN")
    if not votes or locked == "UNKNOWN":
        return 0
    recent = list(votes)[-int(get_cfg("embedding_history_size", 25)) :]
    if not recent:
        return 0
    agree = sum(1 for name, _, _ in recent if name == locked)
    return int(100 * agree / len(recent))


def lock_state(track: dict) -> str:
    locked = track.get("locked_name", "UNKNOWN")
    if locked != "UNKNOWN":
        return "locked"
    if track.get("pending_name"):
        return "pending"
    return "unknown"


def _resolve_frame_candidate(track: dict, result: MatchResult) -> tuple:
    locked = track.get("locked_name", "UNKNOWN")
    retain_th = float(get_cfg("lock_retain_threshold", 0.40))
    release_th = float(get_cfg("lock_release_threshold", 0.32))

    dist = result.distance if result.distance >= 0 else max(0.0, 1.0 - result.best_score)

    if result.accepted:
        return result.name, result.best_score, dist

    if locked != "UNKNOWN":
        if result.name == locked and result.best_score >= retain_th:
            return locked, result.best_score, dist
        if result.best_score >= release_th and result.name == locked:
            return locked, result.best_score, dist
        if result.best_score < release_th:
            track["lock_release_streak"] = track.get("lock_release_streak", 0) + 1
        else:
            track["lock_release_streak"] = 0
            return locked, result.best_score, dist

    return "UNKNOWN", result.best_score, dist


def update_locked_identity(track: dict, candidate_name: str, candidate_score: float):
    now = time.time()
    hold_sec = float(get_cfg("identity_hold_seconds", 1.0))
    miss_limit = int(get_cfg("recognition_misses", 4))
    min_lock = float(get_cfg("min_lock_score", 0.62))
    confirm_need = int(get_cfg("lock_confirm_frames", 6))
    release_streak_need = int(get_cfg("lock_release_streak", 3))

    if candidate_name == "UNKNOWN":
        track["lock_confirm_streak"] = 0
        locked = track.get("locked_name", "UNKNOWN")
        if locked != "UNKNOWN":
            if track.get("lock_release_streak", 0) < release_streak_need:
                track["miss_count"] = track.get("miss_count", 0) + 1
                if track["miss_count"] < miss_limit:
                    return
            track["locked_name"] = "UNKNOWN"
            track["locked_score"] = None
            track["locked_distance"] = None
            track["pending_name"] = None
            track["pending_since"] = 0.0
            track["lock_release_streak"] = 0
            return
        track["miss_count"] = track.get("miss_count", 0) + 1
        return

    track["miss_count"] = 0
    track["lock_release_streak"] = 0
    locked = track.get("locked_name", "UNKNOWN")

    if locked == "UNKNOWN":
        if candidate_score < min_lock:
            track["pending_name"] = None
            track["pending_since"] = 0.0
            track["lock_confirm_streak"] = 0
            return
        if track.get("pending_name") != candidate_name:
            track["pending_name"] = candidate_name
            track["pending_since"] = now
            track["lock_confirm_streak"] = 1
        else:
            track["lock_confirm_streak"] = track.get("lock_confirm_streak", 0) + 1
        if (
            (now - track.get("pending_since", now)) >= hold_sec
            and track.get("lock_confirm_streak", 0) >= confirm_need
        ):
            track["locked_name"] = candidate_name
            track["locked_score"] = candidate_score
            track["locked_since"] = now
            track["pending_name"] = None
            _log(f"locked={candidate_name} score={candidate_score:.3f}")
        return

    if candidate_name == locked:
        track["locked_score"] = candidate_score
        track["pending_name"] = None
        return

    if track.get("pending_name") != candidate_name:
        track["pending_name"] = candidate_name
        track["pending_since"] = now
        track["lock_confirm_streak"] = 1
    else:
        track["lock_confirm_streak"] = track.get("lock_confirm_streak", 0) + 1

    if (
        (now - track.get("pending_since", now)) >= hold_sec
        and track.get("lock_confirm_streak", 0) >= confirm_need
    ):
        _log(f"switch {locked} -> {candidate_name} score={candidate_score:.3f}")
        track["locked_name"] = candidate_name
        track["locked_score"] = candidate_score
        track["locked_since"] = now
        track["pending_name"] = None


def apply_embedding_to_track(face_db: dict, track: dict, embedding):
    if face_db:
        sync_gallery(face_db)

    if embedding is None:
        update_locked_identity(track, "UNKNOWN", -1.0)
        track["last_distance"] = None
        track["stability_pct"] = 0
        track["lock_state"] = lock_state(track)
        track["last_reject_reason"] = "no_embedding"
        return

    hist_len = int(get_cfg("embedding_history_size", 25))
    history = track.setdefault("embedding_history", deque(maxlen=hist_len))
    votes = track.setdefault("vote_history", deque(maxlen=hist_len))

    history.append(embedding)
    fused = fuse_embedding_history(history)
    if fused is None:
        update_locked_identity(track, "UNKNOWN", -1.0)
        return

    locked = track.get("locked_name", "UNKNOWN")
    result = match_identity_detailed(
        fused, locked_name=locked if locked != "UNKNOWN" else None
    )
    track["last_match_score"] = result.best_score
    track["last_match_margin"] = result.margin
    track["last_reject_reason"] = result.reject_reason
    track["last_best_name"] = result.name

    frame_name, frame_score, frame_dist = _resolve_frame_candidate(track, result)
    votes.append((frame_name, frame_score, time.time()))

    vote_name, vote_score, vote_ratio = weighted_vote_name(votes)
    if vote_name != "UNKNOWN":
        candidate_name = vote_name
        candidate_score = vote_score
        candidate_dist = frame_dist if frame_name == vote_name else 1.0 - vote_score
    else:
        candidate_name = frame_name
        candidate_score = frame_score
        candidate_dist = frame_dist

    update_locked_identity(track, candidate_name, candidate_score)

    track["last_embedding"] = fused
    track["last_raw_name"] = result.name
    track["last_distance"] = candidate_dist if candidate_dist >= 0 else None
    track["vote_ratio"] = vote_ratio
    track["stability_pct"] = stability_percent(track)
    track["lock_state"] = lock_state(track)
    track["locked_distance"] = (
        track.get("last_distance") if track.get("locked_name") != "UNKNOWN" else None
    )


def _log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    path = get_cfg("log_file", "logs.txt")
    try:
        with open(path, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass
