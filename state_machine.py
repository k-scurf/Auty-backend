"""
Central AI state machine — all high-level behavior states route through here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, List, Optional, Set

if TYPE_CHECKING:
    from timing_controller import TimingController

from event_system import (
    Event,
    FaceDetected,
    FaceLost,
    FaceRecognized,
    StateChanged,
    UnknownFaceDetected,
)


class AIState(str, Enum):
    IDLE = "IDLE"
    DETECTING = "DETECTING"
    RECOGNIZED = "RECOGNIZED"
    UNKNOWN = "UNKNOWN"
    ALERT = "ALERT"
    ENGAGED = "ENGAGED"


@dataclass
class FSMContext:
    has_faces: bool = False
    active_track_ids: Set[int] = field(default_factory=set)
    primary_track_id: Optional[int] = None
    primary_name: str = "UNKNOWN"
    primary_stable: bool = False
    face_lost_since: Optional[float] = None
    unknown_since: Optional[float] = None
    engaged_until: float = 0.0


class StateMachine:
    def __init__(self, settings: dict):
        self.settings = settings
        self.state = AIState.IDLE
        self.ctx = FSMContext()
        ai = settings.get("ai_states", {})
        self._face_lost_idle = float(ai.get("face_lost_idle_seconds", 3.0))
        self._unknown_alert_sec = float(ai.get("unknown_alert_seconds", 8.0))
        self._engaged_timeout = float(ai.get("engaged_timeout_seconds", 12.0))
        self._detecting_lost_quick = float(ai.get("detecting_lost_quick_seconds", 1.0))
        self._timing: Optional["TimingController"] = None

    def set_timing_controller(self, timing: "TimingController"):
        self._timing = timing

    @property
    def state_value(self) -> str:
        return self.state.value

    def process_events(self, events: List[Event], now: Optional[float] = None) -> List[StateChanged]:
        now = now or time.time()
        transitions: List[StateChanged] = []

        def apply(tr: Optional[StateChanged]):
            if tr is not None:
                transitions.append(tr)

        for event in events:
            if isinstance(event, FaceDetected):
                apply(self._on_face_detected(event, now))
            elif isinstance(event, FaceLost):
                apply(self._on_face_lost(event, now))
            elif isinstance(event, FaceRecognized):
                apply(self._on_face_recognized(event, now))
            elif isinstance(event, UnknownFaceDetected):
                apply(self._on_unknown(event, now))

        for tr in self._tick_timers(now):
            apply(tr)
        return transitions

    def update_context(
        self,
        *,
        has_faces: bool,
        active_track_ids: Set[int],
        primary_track_id: Optional[int],
        primary_name: str,
        primary_stable: bool,
    ):
        self.ctx.has_faces = has_faces
        self.ctx.active_track_ids = set(active_track_ids)
        self.ctx.primary_track_id = primary_track_id
        self.ctx.primary_name = primary_name or "UNKNOWN"
        self.ctx.primary_stable = primary_stable

    def trigger_engaged(self, duration: Optional[float] = None):
        hold = duration if duration is not None else self._engaged_timeout
        self.ctx.engaged_until = time.time() + hold
        self._transition(AIState.ENGAGED, "interaction_started")

    def _on_face_detected(self, event: FaceDetected, now: float) -> Optional[StateChanged]:
        self.ctx.active_track_ids.add(event.track_id)
        self.ctx.has_faces = True
        self.ctx.face_lost_since = None
        if self.state == AIState.IDLE:
            return self._transition(AIState.DETECTING, "face_detected")
        return None

    def _on_face_lost(self, event: FaceLost, now: float) -> Optional[StateChanged]:
        self.ctx.active_track_ids.discard(event.track_id)
        if not self.ctx.active_track_ids:
            self.ctx.has_faces = False
            if self.ctx.face_lost_since is None:
                self.ctx.face_lost_since = now
        return None

    def _on_face_recognized(self, event: FaceRecognized, now: float) -> Optional[StateChanged]:
        self.ctx.unknown_since = None
        if self._timing and self._timing.should_hold_detecting():
            if self.state == AIState.IDLE:
                return self._transition(AIState.DETECTING, "face_detected")
            return None
        if self.state in (AIState.IDLE, AIState.DETECTING, AIState.UNKNOWN, AIState.ALERT):
            return self._transition(AIState.RECOGNIZED, f"recognized_{event.name}")
        return None

    def _on_unknown(self, event: UnknownFaceDetected, now: float) -> Optional[StateChanged]:
        if self.ctx.unknown_since is None:
            self.ctx.unknown_since = now
        if self.state in (AIState.IDLE, AIState.DETECTING, AIState.RECOGNIZED):
            return self._transition(AIState.UNKNOWN, "unknown_face")
        return None

    def _tick_timers(self, now: float) -> List[StateChanged]:
        out: List[StateChanged] = []

        if self.ctx.engaged_until > now and self.state != AIState.ENGAGED:
            tr = self._transition(AIState.ENGAGED, "engaged_timer")
            if tr:
                out.append(tr)
        elif self.ctx.engaged_until <= now and self.state == AIState.ENGAGED:
            if not self.ctx.has_faces:
                target = AIState.IDLE
            elif self.ctx.primary_stable and self.ctx.primary_name != "UNKNOWN":
                target = AIState.RECOGNIZED
            else:
                target = AIState.DETECTING
            tr = self._transition(target, "engaged_timeout")
            if tr:
                out.append(tr)

        if not self.ctx.has_faces and self.ctx.face_lost_since is not None:
            lost_for = now - self.ctx.face_lost_since
            limit = self._detecting_lost_quick if self.state == AIState.DETECTING else self._face_lost_idle
            if lost_for >= limit and self.state != AIState.IDLE:
                tr = self._transition(AIState.IDLE, "face_lost_timeout")
                if tr:
                    out.append(tr)
                self.ctx.face_lost_since = None
                self.ctx.unknown_since = None

        if self._timing:
            if self._timing.should_suggest_idle() and not self.ctx.has_faces:
                if self.state != AIState.IDLE:
                    tr = self._transition(AIState.IDLE, "timing_no_face")
                    if tr:
                        out.append(tr)
                    self.ctx.face_lost_since = None
                    self.ctx.unknown_since = None

            if (
                self._timing.should_suggest_engaged()
                and self.ctx.primary_name != "UNKNOWN"
                and self.ctx.primary_stable
                and self.state in (AIState.RECOGNIZED, AIState.DETECTING)
            ):
                self.ctx.engaged_until = now + self._engaged_timeout
                tr = self._transition(AIState.ENGAGED, "timing_present")
                if tr:
                    out.append(tr)

            if self.state == AIState.UNKNOWN and self._timing.should_escalate_unknown_alert():
                tr = self._transition(AIState.ALERT, "unknown_ramp")
                if tr:
                    out.append(tr)
        elif (
            self.state == AIState.UNKNOWN
            and self.ctx.unknown_since is not None
            and (now - self.ctx.unknown_since) >= self._unknown_alert_sec
        ):
            tr = self._transition(AIState.ALERT, "unknown_persist")
            if tr:
                out.append(tr)

        return out

    def _transition(self, new_state: AIState, reason: str) -> Optional[StateChanged]:
        if new_state == self.state:
            return None
        prev = self.state
        self.state = new_state
        return StateChanged(
            previous_state=prev.value,
            new_state=new_state.value,
            reason=reason,
        )
