"""
Attention / focus logic — primary target + secondary faces for multi-person scenes.
Replaces/extends basic attention.py scoring with recency and unknown penalties.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    from timing_controller import TimingController


def _bbox_area(track: dict) -> float:
    b = track.get("smooth_bbox") or track.get("bbox", (0, 0, 0, 0))
    return float(b[2] * b[3])


def _bbox_center(track: dict) -> Tuple[float, float]:
    b = track.get("smooth_bbox") or track.get("bbox", (0, 0, 0, 0))
    return (b[0] + b[2] * 0.5, b[1] + b[3] * 0.5)


@dataclass
class AttentionResult:
    """Output consumed by HUD, response engine, and FSM context."""

    primary_track_id: Optional[int] = None
    primary_track: Optional[dict] = None
    secondary_track_ids: List[int] = field(default_factory=list)
    secondary_tracks: List[dict] = field(default_factory=list)


class AttentionManager:
    def __init__(self, settings: dict):
        self.settings = settings
        self._current_primary: Optional[int] = None
        self._switch_margin = float(settings.get("attention_switch_margin", 1.25))
        self._center_weight = float(settings.get("attention_center_weight", 0.35))
        self._unknown_penalty = float(settings.get("attention_unknown_penalty", 0.25))
        self._timing: Optional["TimingController"] = None
        self._last_result = AttentionResult()

    def set_timing_controller(self, timing: "TimingController"):
        self._timing = timing

    @property
    def primary_track_id(self) -> Optional[int]:
        return self._current_primary

    @property
    def last_result(self) -> AttentionResult:
        return self._last_result

    def select(
        self, tracks: List[dict], frame_size: Tuple[int, int]
    ) -> AttentionResult:
        """Score all tracks; return primary + ordered secondary list."""
        if not tracks:
            self._current_primary = None
            self._last_result = AttentionResult()
            return self._last_result

        fw, fh = frame_size
        cx_frame, cy_frame = fw * 0.5, fh * 0.5
        max_area = max(_bbox_area(t) for t in tracks) or 1.0
        multi_face = len(tracks) > 1

        def score(track: dict) -> float:
            area = _bbox_area(track)
            tcx, tcy = _bbox_center(track)
            dist = ((tcx - cx_frame) ** 2 + (tcy - cy_frame) ** 2) ** 0.5
            max_dist = (fw**2 + fh**2) ** 0.5
            center_score = 1.0 - min(1.0, dist / max_dist)
            area_norm = area / max_area
            name = track.get("locked_name", "UNKNOWN")
            known_bonus = 0.18 if name != "UNKNOWN" else 0.0
            unknown_pen = 0.0
            if multi_face and name == "UNKNOWN":
                unknown_pen = self._unknown_penalty
            recency = 0.0
            if self._timing is not None:
                recency = self._timing.recency_boost(track["id"])
            return area_norm + self._center_weight * center_score + known_bonus + recency - unknown_pen

        ranked = sorted(tracks, key=score, reverse=True)
        best = ranked[0]
        best_id = best["id"]

        if self._current_primary is not None:
            current = next((t for t in tracks if t["id"] == self._current_primary), None)
            if current is not None:
                cur_score = score(current)
                if score(best) < cur_score * self._switch_margin:
                    best = current
                    best_id = current["id"]

        self._current_primary = best_id
        secondaries = [t for t in ranked if t["id"] != best_id]

        self._last_result = AttentionResult(
            primary_track_id=best_id,
            primary_track=best,
            secondary_track_ids=[t["id"] for t in secondaries],
            secondary_tracks=secondaries,
        )
        return self._last_result

    def select_primary(
        self, tracks: List[dict], frame_size: Tuple[int, int]
    ) -> Optional[dict]:
        """Backward-compatible API — returns primary track dict only."""
        return self.select(tracks, frame_size).primary_track
