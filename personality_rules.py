"""
State-based personality consistency — tone, UI motion, and response pacing.
Connects FSM state → mood/status/greeting style (used by ResponseEngine).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from personality_engine import Mood
from state_machine import AIState


class UIMotion(str, Enum):
    MINIMAL = "minimal"
    SMOOTH = "smooth"
    CAUTIOUS = "cautious"
    ALERT = "alert"


@dataclass(frozen=True)
class ToneProfile:
    """How Auty should feel/act in a given AI state."""

    mood: Mood
    ui_motion: UIMotion
    greeting_delay_ms: int
    status_prefix: str
    speak_enabled: bool
    effects_intensity: float  # 0–1 for ui_effects scaling


# Defaults tuned for demo-quality: calm idle, warm engaged, cautious unknown.
_STATE_PROFILES: dict[AIState, ToneProfile] = {
    AIState.IDLE: ToneProfile(
        mood=Mood.CALM,
        ui_motion=UIMotion.MINIMAL,
        greeting_delay_ms=400,
        status_prefix="Standing by",
        speak_enabled=False,
        effects_intensity=0.35,
    ),
    AIState.DETECTING: ToneProfile(
        mood=Mood.CURIOUS,
        ui_motion=UIMotion.SMOOTH,
        greeting_delay_ms=350,
        status_prefix="Observing",
        speak_enabled=False,
        effects_intensity=0.5,
    ),
    AIState.RECOGNIZED: ToneProfile(
        mood=Mood.FRIENDLY,
        ui_motion=UIMotion.SMOOTH,
        greeting_delay_ms=250,
        status_prefix="Recognized",
        speak_enabled=True,
        effects_intensity=0.65,
    ),
    AIState.UNKNOWN: ToneProfile(
        mood=Mood.SUSPICIOUS,
        ui_motion=UIMotion.CAUTIOUS,
        greeting_delay_ms=500,
        status_prefix="Unknown visitor",
        speak_enabled=False,
        effects_intensity=0.55,
    ),
    AIState.ALERT: ToneProfile(
        mood=Mood.ALERT,
        ui_motion=UIMotion.ALERT,
        greeting_delay_ms=600,
        status_prefix="Alert",
        speak_enabled=True,
        effects_intensity=0.85,
    ),
    AIState.ENGAGED: ToneProfile(
        mood=Mood.EXCITED,
        ui_motion=UIMotion.SMOOTH,
        greeting_delay_ms=200,
        status_prefix="Engaged",
        speak_enabled=True,
        effects_intensity=0.75,
    ),
}


class PersonalityRules:
    """Maps FSM state (+ optional familiarity) to consistent behavior parameters."""

    def __init__(self, settings: dict):
        self.settings = settings
        self._familiar_boost_delay_ms = int(
            settings.get("behavior_timing", {}).get(
                "familiar_greeting_delay_ms", 180
            )
        )

    def profile_for_state(self, state: str, *, familiar: bool = False) -> ToneProfile:
        try:
            enum_state = AIState(state)
        except ValueError:
            enum_state = AIState.IDLE
        base = _STATE_PROFILES.get(enum_state, _STATE_PROFILES[AIState.IDLE])
        if not familiar:
            return base
        return ToneProfile(
            mood=base.mood,
            ui_motion=base.ui_motion,
            greeting_delay_ms=max(
                self._familiar_boost_delay_ms, base.greeting_delay_ms - 80
            ),
            status_prefix=base.status_prefix,
            speak_enabled=base.speak_enabled,
            effects_intensity=min(1.0, base.effects_intensity + 0.1),
        )

    def compose_status_line(self, state: str, mood: Mood, familiar: bool = False) -> str:
        prof = self.profile_for_state(state, familiar=familiar)
        suffix = " · familiar" if familiar else ""
        return f"{prof.status_prefix}{suffix} · {mood.value}"

    def should_use_idle_scan(self, state: str) -> bool:
        return state in (AIState.IDLE.value, AIState.DETECTING.value)
