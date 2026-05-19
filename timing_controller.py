"""
Time-based behavior — per-face and session timers that guide FSM transitions.
Integrates with StateMachine._tick_timers (does not replace the event bus).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class FaceTiming:
    track_id: int
    first_seen: float
    last_seen: float
    locked_name: str = "UNKNOWN"
    recognized_since: Optional[float] = None


@dataclass
class SessionTiming:
    session_started: float = field(default_factory=time.time)
    first_face_at: Optional[float] = None
    last_face_at: Optional[float] = None
    no_face_since: Optional[float] = None
    primary_present_since: Optional[float] = None
    primary_name: str = "UNKNOWN"


class TimingController:
    def __init__(self, settings: dict):
        self.settings = settings
        bt = settings.get("behavior_timing", {})
        ai = settings.get("ai_states", {})
        self._detecting_max = float(bt.get("detecting_max_seconds", 2.0))
        self._engaged_after = float(bt.get("engaged_after_present_seconds", 3.0))
        self._idle_after_no_face = float(
            bt.get("idle_after_no_face_seconds", ai.get("face_lost_idle_seconds", 5.0))
        )
        self._familiar_after = float(bt.get("familiar_after_recognized_seconds", 10.0))
        self._unknown_alert_ramp = float(
            bt.get("unknown_alert_ramp_seconds", ai.get("unknown_alert_seconds", 12.0))
        )
        self._recency_boost_sec = float(bt.get("recency_attention_boost_seconds", 1.5))

        self._faces: Dict[int, FaceTiming] = {}
        self.session = SessionTiming()
        self._unknown_present_since: Optional[float] = None

    def update(
        self,
        tracks: List[dict],
        primary_track_id: Optional[int],
        primary_name: str,
        now: Optional[float] = None,
    ):
        now = now or time.time()
        active_ids: Set[int] = set()

        for t in tracks:
            tid = t["id"]
            active_ids.add(tid)
            name = t.get("locked_name", "UNKNOWN")
            ft = self._faces.get(tid)
            if ft is None:
                ft = FaceTiming(track_id=tid, first_seen=now, last_seen=now, locked_name=name)
                self._faces[tid] = ft
            ft.last_seen = now
            ft.locked_name = name
            if name != "UNKNOWN" and ft.recognized_since is None:
                ft.recognized_since = now

        for tid in list(self._faces.keys()):
            if tid not in active_ids:
                del self._faces[tid]

        if tracks:
            if self.session.first_face_at is None:
                self.session.first_face_at = now
            self.session.last_face_at = now
            self.session.no_face_since = None
            if primary_track_id is not None:
                if self.session.primary_present_since is None or self.session.primary_name != primary_name:
                    self.session.primary_present_since = now
                self.session.primary_name = primary_name
        else:
            if self.session.no_face_since is None:
                self.session.no_face_since = now
            self.session.primary_present_since = None

        if primary_name == "UNKNOWN" and tracks:
            if self._unknown_present_since is None:
                self._unknown_present_since = now
        else:
            self._unknown_present_since = None

    def primary_present_duration(self, now: Optional[float] = None) -> float:
        now = now or time.time()
        if self.session.primary_present_since is None:
            return 0.0
        return now - self.session.primary_present_since

    def no_face_duration(self, now: Optional[float] = None) -> float:
        now = now or time.time()
        if self.session.no_face_since is None:
            return 0.0
        return now - self.session.no_face_since

    def is_familiar_session(self, name: str, now: Optional[float] = None) -> bool:
        """Same recognized user in view for familiar_after seconds."""
        now = now or time.time()
        if name == "UNKNOWN":
            return False
        for ft in self._faces.values():
            if ft.locked_name == name and ft.recognized_since is not None:
                if (now - ft.recognized_since) >= self._familiar_after:
                    return True
        return False

    def recency_boost(self, track_id: int, now: Optional[float] = None) -> float:
        """0–0.2 score boost for recently active tracks (attention)."""
        now = now or time.time()
        ft = self._faces.get(track_id)
        if ft is None:
            return 0.0
        age = now - ft.last_seen
        if age > self._recency_boost_sec:
            return 0.0
        return 0.2 * (1.0 - age / self._recency_boost_sec)

    def unknown_alert_progress(self, now: Optional[float] = None) -> float:
        """0.0 → 1.0 ramp for gradual ALERT escalation."""
        now = now or time.time()
        if self._unknown_present_since is None:
            return 0.0
        elapsed = now - self._unknown_present_since
        if self._unknown_alert_ramp <= 0:
            return 1.0
        return min(1.0, elapsed / self._unknown_alert_ramp)

    def should_hold_detecting(self, now: Optional[float] = None) -> bool:
        """Face present less than detecting_max → stay in DETECTING."""
        return self.primary_present_duration(now) < self._detecting_max

    def should_suggest_engaged(self, now: Optional[float] = None) -> bool:
        return self.primary_present_duration(now) >= self._engaged_after

    def should_suggest_idle(self, now: Optional[float] = None) -> bool:
        return self.no_face_duration(now) >= self._idle_after_no_face

    def should_escalate_unknown_alert(self, now: Optional[float] = None) -> bool:
        return self.unknown_alert_progress(now) >= 1.0

    def reset(self):
        self._faces.clear()
        self.session = SessionTiming()
        self._unknown_present_since = None
