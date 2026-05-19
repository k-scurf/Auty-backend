"""
Map detection events and moods to HUD color themes.
"""

from personality_engine import Mood
from state_machine import AIState


# RGBA tuples for PIL / OpenCV BGR conversion in ui_overlay
HUD_THEMES = {
    Mood.CALM: {
        "border": (0, 200, 190, 255),
        "glow": (0, 140, 130, 60),
        "accent": (90, 230, 220, 255),
        "muted": (150, 180, 175, 255),
        "bar": (0, 190, 170, 255),
        "label": (110, 140, 135, 255),
        "known": True,
    },
    Mood.FRIENDLY: {
        "border": (0, 255, 220, 255),
        "glow": (0, 180, 160, 80),
        "accent": (100, 255, 235, 255),
        "muted": (160, 190, 200, 255),
        "bar": (0, 220, 180, 255),
        "label": (120, 150, 165, 255),
        "known": True,
    },
    Mood.CURIOUS: {
        "border": (0, 220, 255, 255),
        "glow": (0, 160, 220, 70),
        "accent": (120, 220, 255, 255),
        "muted": (160, 190, 210, 255),
        "bar": (0, 200, 255, 255),
        "label": (120, 150, 180, 255),
        "known": True,
    },
    Mood.EXCITED: {
        "border": (0, 255, 200, 255),
        "glow": (0, 200, 120, 90),
        "accent": (150, 255, 180, 255),
        "muted": (180, 210, 190, 255),
        "bar": (0, 255, 150, 255),
        "label": (130, 160, 140, 255),
        "known": True,
    },
    Mood.ALERT: {
        "border": (255, 120, 40, 255),
        "glow": (255, 80, 20, 80),
        "accent": (255, 170, 100, 255),
        "muted": (200, 170, 150, 255),
        "bar": (255, 100, 50, 255),
        "label": (180, 140, 120, 255),
        "known": False,
    },
    Mood.SUSPICIOUS: {
        "border": (255, 80, 60, 255),
        "glow": (255, 40, 30, 90),
        "accent": (255, 140, 90, 255),
        "muted": (190, 150, 140, 255),
        "bar": (255, 70, 40, 255),
        "label": (170, 120, 110, 255),
        "known": False,
    },
}


def mood_for_identity(name: str, tier: str, has_faces: bool, state: AIState) -> Mood:
    if not has_faces:
        return Mood.CALM
    if name == "UNKNOWN" or tier == "UNKNOWN":
        return Mood.ALERT if state == AIState.ALERT else Mood.SUSPICIOUS
    if tier == "OWNER":
        return Mood.FRIENDLY
    if state == AIState.ENGAGED:
        return Mood.EXCITED
    if state == AIState.RECOGNIZED:
        return Mood.FRIENDLY
    if state == AIState.DETECTING:
        return Mood.CURIOUS
    return Mood.FRIENDLY


def theme_for_mood(mood: Mood, known: bool = True) -> dict:
    t = HUD_THEMES.get(mood, HUD_THEMES[Mood.CALM])
    if not known and mood not in (Mood.CALM, Mood.CURIOUS):
        t = HUD_THEMES[Mood.ALERT]
    return t
