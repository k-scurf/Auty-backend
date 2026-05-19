"""
Response throttling — prevents spammy greetings, duplicate event reactions, and voice floods.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional, Set


@dataclass
class _PendingBatch:
    event_key: str
    payload: Any
    created_at: float


class ResponseThrottler:
    def __init__(self, settings: dict):
        self.settings = settings
        beh = settings.get("behavior_throttle", {})
        self._greet_cooldown = float(
            beh.get("greeting_cooldown_seconds", settings.get("greeting_cooldown_seconds", 20.0))
        )
        self._voice_min_gap = float(beh.get("voice_min_gap_seconds", 4.0))
        self._event_cooldown = float(beh.get("event_cooldown_seconds", 2.0))
        self._batch_window_ms = float(beh.get("batch_window_ms", 150.0))

        self._last_greet: Dict[str, float] = {}
        self._last_voice_at: float = 0.0
        self._last_event_at: Dict[str, float] = {}
        self._handled_event_keys: Set[str] = set()
        self._last_state: Optional[str] = None
        self._pending: Deque[_PendingBatch] = deque(maxlen=32)

    def on_state_changed(self, new_state: str):
        """Allow event reactions again when FSM state changes."""
        if new_state != self._last_state:
            self._handled_event_keys.clear()
            self._last_state = new_state

    def allow_greeting(self, name: str, *, familiar: bool = False) -> bool:
        if name == "UNKNOWN":
            return False
        cooldown = self._greet_cooldown
        if familiar:
            cooldown = max(cooldown, self._greet_cooldown * 1.5)
        last = self._last_greet.get(name, 0.0)
        return (time.time() - last) >= cooldown

    def record_greeting(self, name: str):
        self._last_greet[name] = time.time()
        self._last_voice_at = time.time()

    def allow_voice(self) -> bool:
        return (time.time() - self._last_voice_at) >= self._voice_min_gap

    def record_voice(self):
        self._last_voice_at = time.time()

    def allow_event_reaction(self, event_key: str, *, force_on_state_change: bool = True) -> bool:
        """
        event_key e.g. 'face_recognized:Kerrington' or 'unknown:3'.
        Skips duplicate reactions unless state just changed.
        """
        now = time.time()
        if event_key in self._handled_event_keys:
            return False
        last = self._last_event_at.get(event_key, 0.0)
        if (now - last) < self._event_cooldown:
            return False
        return True

    def mark_event_handled(self, event_key: str):
        self._last_event_at[event_key] = time.time()
        self._handled_event_keys.add(event_key)

    def queue_batch(self, event_key: str, payload: Any):
        """Coalesce rapid duplicate events within batch_window_ms."""
        self._pending.append(_PendingBatch(event_key, payload, time.time()))

    def pop_batched(self) -> Optional[_PendingBatch]:
        if not self._pending:
            return None
        now = time.time()
        window = self._batch_window_ms / 1000.0
        first = self._pending[0]
        if (now - first.created_at) < window and len(self._pending) > 1:
            return None
        return self._pending.popleft()
