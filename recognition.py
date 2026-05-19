"""
Production recognition pipeline for Auty.

Components:
  - ArcFace embeddings (DeepFace), L2-normalized for cosine matching
  - MediaPipe Face Mesh alignment (5-point affine) with padded-crop fallback
  - Multi-embedding database: best score per person across all stored samples
  - Temporal fusion: embedding history mean + weighted vote consensus
  - Identity lock: ~1s hold before switching; grace period on brief UNKNOWN
"""

from collections import Counter, deque
import time

import cv2
import numpy as np

# Optional MediaPipe (protobuf conflicts on some installs — safe fallback).
_mp_face_mesh = None
_alignment_warned = False

try:
    import mediapipe as mp

    _mp_face_mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
except Exception:
    _mp_face_mesh = None

_deepface = None

CFG = {
    "model_name": "ArcFace",
    "detector_backend": "opencv",
    "confidence_threshold": 0.40,
    "min_lock_score": 0.55,
    "score_margin": 0.03,
    "embedding_history_size": 25,
    "identity_hold_seconds": 1.0,
    "recognition_misses": 4,
    "min_vote_ratio": 0.55,
    "vote_min_frames": 5,
    "use_face_alignment": True,
    "debug_scores": False,
    "log_file": "logs.txt",
}

ALIGN_SIZE = (112, 112)

# MediaPipe Face Mesh indices (eye centers, nose, mouth corners).
_LM_LEFT_EYE = (33, 133, 160, 159, 158)
_LM_RIGHT_EYE = (263, 362, 385, 386, 387)
_LM_NOSE = 1
_LM_MOUTH_L = 61
_LM_MOUTH_R = 291

# Canonical 5-point positions for 112x112 ArcFace-style crops.
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


def configure(settings: dict):
    CFG.update(settings)


def _warn_alignment_once(msg: str):
    global _alignment_warned
    if not _alignment_warned:
        print(f"[recognition] {msg}")
        _alignment_warned = True


def is_embedding(value) -> bool:
    try:
        arr = np.asarray(value, dtype=np.float32)
    except (TypeError, ValueError):
        return False
    return arr.ndim == 1 and arr.size > 0 and np.isfinite(arr).all()


def l2_normalize(embedding):
    arr = np.asarray(embedding, dtype=np.float32).flatten()
    norm = np.linalg.norm(arr)
    if norm < 1e-9:
        return arr
    return (arr / norm).tolist()


def cosine_similarity(a, b) -> float:
    va = np.asarray(a, dtype=np.float32).flatten()
    vb = np.asarray(b, dtype=np.float32).flatten()
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom < 1e-9:
        return -1.0
    return float(np.dot(va, vb) / denom)


def cosine_distance(a, b) -> float:
    """ArcFace distance metric: 1 - cosine similarity (lower is better)."""
    return 1.0 - cosine_similarity(a, b)


def padded_crop(frame, x, y, w, h, pad_ratio=0.30):
    pad_x = int(w * pad_ratio)
    pad_y = int(h * pad_ratio)
    frame_h, frame_w = frame.shape[:2]
    x1 = max(x - pad_x, 0)
    y1 = max(y - pad_y, 0)
    x2 = min(x + w + pad_x, frame_w)
    y2 = min(y + h + pad_y, frame_h)
    return frame[y1:y2, x1:x2]


def _landmark_point(lm, idx, w, h):
    p = lm[idx]
    return np.array([p.x * w, p.y * h], dtype=np.float32)


def _mean_landmark(lm, indices, w, h):
    pts = [_landmark_point(lm, i, w, h) for i in indices]
    return np.mean(pts, axis=0).astype(np.float32)


def _align_with_mediapipe(bgr_crop):
    if _mp_face_mesh is None or bgr_crop.size == 0:
        return None

    rgb = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2RGB)
    result = _mp_face_mesh.process(rgb)
    if not result.multi_face_landmarks:
        return None

    h, w = bgr_crop.shape[:2]
    lm = result.multi_face_landmarks[0].landmark

    src = np.array(
        [
            _mean_landmark(lm, _LM_LEFT_EYE, w, h),
            _mean_landmark(lm, _LM_RIGHT_EYE, w, h),
            _landmark_point(lm, _LM_NOSE, w, h),
            _landmark_point(lm, _LM_MOUTH_L, w, h),
            _landmark_point(lm, _LM_MOUTH_R, w, h),
        ],
        dtype=np.float32,
    )

    matrix, _ = cv2.estimateAffinePartial2D(src, _DST_5PT, method=cv2.LMEDS)
    if matrix is None:
        return None
    return cv2.warpAffine(bgr_crop, matrix, ALIGN_SIZE, borderMode=cv2.BORDER_REFLECT)


def align_face(frame, x, y, w, h):
    """Landmark-based alignment (eyes horizontal, standard crop) or padded crop."""
    crop = padded_crop(frame, x, y, w, h)
    if crop.size == 0:
        return crop

    if CFG.get("use_face_alignment", True):
        aligned = _align_with_mediapipe(crop)
        if aligned is not None:
            return aligned
        _warn_alignment_once("MediaPipe alignment unavailable; using padded crop.")

    return crop


def is_aligned_crop(bgr_image) -> bool:
    if bgr_image is None or bgr_image.size == 0:
        return False
    h, w = bgr_image.shape[:2]
    return h == ALIGN_SIZE[1] and w == ALIGN_SIZE[0]


def extract_embedding(bgr_image, *, already_aligned=None):
    """ArcFace via DeepFace; returns L2-normalized vector for cosine matching."""
    global _deepface
    if bgr_image is None or bgr_image.size == 0:
        return None

    if already_aligned is None:
        already_aligned = is_aligned_crop(bgr_image)

    if _deepface is None:
        from deepface import DeepFace

        _deepface = DeepFace

    try:
        result = _deepface.represent(
            img_path=bgr_image,
            model_name=CFG.get("model_name", "ArcFace"),
            detector_backend=CFG.get("detector_backend", "opencv"),
            enforce_detection=False,
            align=not already_aligned,
        )
        return l2_normalize(result[0]["embedding"])
    except Exception as exc:
        if CFG.get("debug_scores", False):
            log_recognition(f"embedding_error={exc}")
        return None


def match_identity(face_db: dict, embedding):
    """
    Compare query against ALL embeddings per person (max score wins).
    Returns (name, confidence, second_best_score, cosine_distance).
    UNKNOWN if below threshold or margin too small — no forced closest match.
    """
    if not face_db or embedding is None:
        return "UNKNOWN", -1.0, -1.0, -1.0

    query = l2_normalize(embedding)
    person_scores = []

    for db_name, embeddings in face_db.items():
        scores = [
            cosine_similarity(query, stored)
            for stored in embeddings
            if is_embedding(stored)
        ]
        if scores:
            person_scores.append((max(scores), db_name))

    if not person_scores:
        return "UNKNOWN", -1.0, -1.0, -1.0

    person_scores.sort(reverse=True)
    best_score, best_name = person_scores[0]
    second_score = person_scores[1][0] if len(person_scores) > 1 else -1.0
    margin = best_score - second_score
    threshold = float(CFG.get("confidence_threshold", 0.40))
    min_margin = float(CFG.get("score_margin", 0.03))
    distance = cosine_distance(query, face_db[best_name][0]) if best_name in face_db else -1.0

    if CFG.get("debug_scores", False):
        samples = len(face_db.get(best_name, []))
        log_recognition(
            f"best={best_name} score={best_score:.3f} second={second_score:.3f} "
            f"margin={margin:.3f} dist={distance:.3f} samples={samples}"
        )

    if best_score < threshold or margin < min_margin:
        return "UNKNOWN", best_score, second_score, 1.0 - best_score if best_score > 0 else -1.0

    # Best distance among this person's embeddings.
    dists = [
        cosine_distance(query, stored)
        for stored in face_db.get(best_name, [])
        if is_embedding(stored)
    ]
    best_dist = min(dists) if dists else 1.0 - best_score

    return best_name, best_score, second_score, best_dist


def fuse_embedding_history(history: deque):
    """Mean of recent embeddings, re-normalized — robust to single bad frames."""
    if not history:
        return None
    stack = np.array(list(history), dtype=np.float32)
    return l2_normalize(np.mean(stack, axis=0))


def weighted_vote_name(vote_history: deque):
    """
    Majority vote weighted by confidence; requires min_vote_ratio agreement.
  """
    min_frames = int(CFG.get("vote_min_frames", 5))
    min_ratio = float(CFG.get("min_vote_ratio", 0.55))

    if len(vote_history) < min_frames:
        return "UNKNOWN", 0.0, 0.0

    weighted = {}
    counts = Counter()
    for name, score, _ts in vote_history:
        if name == "UNKNOWN" or score is None or score < 0:
            counts["UNKNOWN"] += 1
            continue
        counts[name] += 1
        weighted[name] = weighted.get(name, 0.0) + score

    if not weighted:
        return "UNKNOWN", 0.0, counts["UNKNOWN"] / len(vote_history)

    name = max(weighted, key=weighted.get)
    ratio = counts[name] / len(vote_history)
    avg_score = weighted[name] / counts[name]

    if ratio < min_ratio:
        return "UNKNOWN", avg_score, ratio

    return name, avg_score, ratio


def stability_percent(track: dict) -> int:
    """How consistently recent frames agree with the locked identity (0–100)."""
    votes = track.get("vote_history")
    locked = track.get("locked_name", "UNKNOWN")
    if not votes or locked == "UNKNOWN":
        return 0
    recent = list(votes)[-int(CFG.get("embedding_history_size", 25)) :]
    if not recent:
        return 0
    agree = sum(1 for name, _, _ in recent if name == locked)
    return int(100 * agree / len(recent))


def log_recognition(message: str):
    path = CFG.get("log_file", "logs.txt")
    line = f"[{time.strftime('%H:%M:%S')}] {message}\n"
    print(line.strip())
    try:
        with open(path, "a") as f:
            f.write(line)
    except OSError:
        pass


def update_locked_identity(track: dict, candidate_name: str, candidate_score: float):
    """
    Anti-flicker lock: identity switches only after identity_hold_seconds of
    consistent candidate; brief UNKNOWN frames keep the last locked identity.
    """
    now = time.time()
    hold_sec = float(CFG.get("identity_hold_seconds", 1.0))
    miss_limit = int(CFG.get("recognition_misses", 4))

    if candidate_name == "UNKNOWN":
        track["miss_count"] = track.get("miss_count", 0) + 1
        if track.get("locked_name", "UNKNOWN") != "UNKNOWN":
            if track["miss_count"] < miss_limit:
                return
        track["locked_name"] = "UNKNOWN"
        track["locked_score"] = None
        track["locked_distance"] = None
        track["pending_name"] = None
        track["pending_since"] = 0.0
        return

    track["miss_count"] = 0
    locked = track.get("locked_name", "UNKNOWN")

    if locked == "UNKNOWN":
        min_lock = float(CFG.get("min_lock_score", 0.55))
        if candidate_score < min_lock:
            track["pending_name"] = None
            track["pending_since"] = 0.0
            return
        if track.get("pending_name") != candidate_name:
            track["pending_name"] = candidate_name
            track["pending_since"] = now
        elif (now - track.get("pending_since", now)) >= hold_sec:
            track["locked_name"] = candidate_name
            track["locked_score"] = candidate_score
            track["locked_since"] = now
            track["pending_name"] = None
            log_recognition(f"locked={candidate_name} score={candidate_score:.3f}")
        return

    if candidate_name == locked:
        track["locked_score"] = candidate_score
        track["pending_name"] = None
        return

    if track.get("pending_name") != candidate_name:
        track["pending_name"] = candidate_name
        track["pending_since"] = now
    elif (now - track.get("pending_since", now)) >= hold_sec:
        log_recognition(
            f"switch {locked} -> {candidate_name} score={candidate_score:.3f}"
        )
        track["locked_name"] = candidate_name
        track["locked_score"] = candidate_score
        track["locked_since"] = now
        track["pending_name"] = None


def recognize_track(face_db: dict, track: dict, bgr_crop):
    """Embedding + temporal fusion + vote consensus + identity lock."""
    embedding = extract_embedding(bgr_crop, already_aligned=is_aligned_crop(bgr_crop))
    apply_embedding_to_track(face_db, track, embedding)


def apply_embedding_to_track(face_db: dict, track: dict, embedding):
    """Apply a precomputed embedding (e.g. from a background worker thread)."""
    if embedding is None:
        update_locked_identity(track, "UNKNOWN", -1.0)
        track["last_distance"] = None
        track["stability_pct"] = 0
        return

    hist_len = int(CFG.get("embedding_history_size", 25))
    history = track.setdefault("embedding_history", deque(maxlen=hist_len))
    votes = track.setdefault("vote_history", deque(maxlen=hist_len))

    history.append(embedding)
    fused = fuse_embedding_history(history)
    if fused is None:
        update_locked_identity(track, "UNKNOWN", -1.0)
        return

    frame_name, frame_score, _, frame_dist = match_identity(face_db, fused)
    votes.append((frame_name, frame_score, time.time()))

    vote_name, vote_score, vote_ratio = weighted_vote_name(votes)

    # Prefer stable consensus over a single noisy frame.
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
    track["last_raw_name"] = frame_name
    track["last_distance"] = candidate_dist if candidate_dist >= 0 else None
    track["vote_ratio"] = vote_ratio
    track["stability_pct"] = stability_percent(track)
    track["locked_distance"] = (
        track.get("last_distance") if track.get("locked_name") != "UNKNOWN" else None
    )
