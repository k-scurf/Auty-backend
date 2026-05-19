"""
Template-based greetings, moods, and status lines (offline-first).
"""

import random
from enum import Enum


class Mood(str, Enum):
    CALM = "Calm"
    FRIENDLY = "Friendly"
    CURIOUS = "Curious"
    ALERT = "Alert"
    SUSPICIOUS = "Suspicious"
    EXCITED = "Excited"


GREETINGS = {
    "OWNER": [
        "Welcome back, {name}.",
        "Good to see you again, {name}.",
        "Hello, {name}. Systems are ready.",
    ],
    "FRIEND": [
        "Hey, good to see you again, {name}.",
        "Hi {name}, welcome back.",
        "Nice to see you, {name}.",
    ],
    "UNKNOWN": [
        "Unknown individual detected.",
        "Unrecognized face in view.",
        "Alert: unknown person detected.",
    ],
}

GREETINGS_HUMOR = {
    "OWNER": ["Oh look, the boss is back. Hi {name}."],
    "FRIEND": ["{name} has entered the chat."],
    "UNKNOWN": ["Who are you? I literally do not know you."],
}

GREETINGS_SARCASM = {
    "OWNER": ["The VIP has arrived. Welcome, {name}."],
    "FRIEND": ["Wow, it's {name}. What a surprise."],
    "UNKNOWN": ["Stranger danger, but make it polite."],
}

IDLE_LINES = [
    "Scanning for faces…",
    "Standing by.",
    "Ambient watch mode.",
    "No one in frame. Listening.",
    "Systems idle — ready when you are.",
]

SEARCHING_LINES = [
    "Searching…",
    "Where did they go?",
    "Re-acquiring target…",
]


class PersonalityEngine:
    def __init__(self, settings: dict):
        self.settings = settings

    def compose_greeting(self, name: str, tier: str, mood: Mood, memory_line: str = "") -> str:
        pool = GREETINGS.get(tier, GREETINGS["UNKNOWN"])
        if self.settings.get("sarcasm_mode"):
            pool = GREETINGS_SARCASM.get(tier, pool)
        elif self.settings.get("humor_mode"):
            pool = GREETINGS_HUMOR.get(tier, pool)
        display = name if name != "UNKNOWN" else "Unknown"
        line = random.choice(pool).format(name=display)
        if memory_line and tier != "UNKNOWN":
            line = f"{line} {memory_line}"
        return line

    def compose_status(self, state: str, mood: Mood) -> str:
        if state in ("IDLE", "Idle"):
            return random.choice(IDLE_LINES)
        if state in ("DETECTING", "Searching"):
            return random.choice(SEARCHING_LINES)
        return f"{state} · {mood.value}"
