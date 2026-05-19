"""
Detect the user's facial expression (DeepFace emotion model).
Throttled per track so it stays usable on Mac CPU.
"""

from collections import deque

_deepface = None

EMOTION_LABELS = {
    "angry": "Angry",
    "disgust": "Disgusted",
    "fear": "Fearful",
    "happy": "Happy",
    "sad": "Sad",
    "surprise": "Surprised",
    "neutral": "Neutral",
}


class UserEmotionAnalyzer:
    def __init__(self, settings: dict):
        self.settings = settings
        self.enabled = bool(settings.get("user_emotion_enabled", True))
        self.interval = int(settings.get("emotion_interval_frames", 24))
        self.interval_locked = int(
            settings.get("emotion_interval_when_locked", 60)
        )
        self.min_confidence = float(settings.get("emotion_min_confidence", 0.30))
        self.smooth_window = int(settings.get("emotion_smooth_window", 5))

    def interval_for_track(self, track: dict) -> int:
        if not self.enabled:
            return 999999
        if self.settings.get("emotion_skip_when_locked", True):
            if (
                track.get("locked_name", "UNKNOWN") != "UNKNOWN"
                and track.get("stable_count", 0) >= 2
            ):
                return 999999
        if (
            track.get("locked_name", "UNKNOWN") != "UNKNOWN"
            and track.get("stable_count", 0) >= 2
        ):
            return self.interval_locked
        return self.interval

    def maybe_update(self, track: dict, aligned_bgr, frame_count: int):
        if not self.enabled or aligned_bgr is None or getattr(aligned_bgr, "size", 0) == 0:
            return
        interval = self.interval_for_track(track)
        if frame_count - track.get("last_emotion_frame", -999) < interval:
            return
        track["last_emotion_frame"] = frame_count

        label, score = self._analyze(aligned_bgr)
        if not label:
            return

        hist = track.setdefault("emotion_history", deque(maxlen=self.smooth_window))
        hist.append((label, score))

        # Weighted vote by confidence
        totals = {}
        for em, sc in hist:
            totals[em] = totals.get(em, 0.0) + sc
        best = max(totals, key=totals.get)
        avg_score = totals[best] / len(hist)
        track["user_emotion"] = best
        track["user_emotion_pct"] = int(round(avg_score * 100))

    def display_label(self, track: dict) -> str:
        raw = track.get("user_emotion")
        if not raw:
            return "—"
        name = EMOTION_LABELS.get(raw, raw.title())
        pct = track.get("user_emotion_pct")
        if pct is not None:
            return f"{name} ({pct}%)"
        return name

    def _analyze(self, aligned_bgr):
        global _deepface
        if _deepface is None:
            try:
                from deepface import DeepFace

                _deepface = DeepFace
            except ImportError:
                return None, 0.0

        try:
            objs = _deepface.analyze(
                img_path=aligned_bgr,
                actions=["emotion"],
                enforce_detection=False,
                detector_backend="skip",
                align=False,
            )
            if not objs:
                return None, 0.0
            probs = objs[0].get("emotion") or {}
            if not probs:
                return None, 0.0
            top = max(probs, key=probs.get)
            score = float(probs[top]) / 100.0
            if score < self.min_confidence:
                return None, 0.0
            return top, score
        except Exception:
            return None, 0.0
