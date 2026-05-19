"""
Event bus for Auty — perception and AI core communicate via typed events only.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Type


@dataclass
class Event:
    """Base event; use typed subclasses below."""

    timestamp: float = 0.0
    frame_count: int = 0


@dataclass
class FaceDetected(Event):
    track_id: int = 0
    bbox: tuple = (0, 0, 0, 0)


@dataclass
class FaceLost(Event):
    track_id: int = 0


@dataclass
class FaceRecognized(Event):
    track_id: int = 0
    name: str = ""
    confidence: float = 0.0


@dataclass
class UnknownFaceDetected(Event):
    track_id: int = 0
    confidence: float = 0.0


@dataclass
class EmotionUpdated(Event):
    track_id: int = 0
    emotion: str = ""
    confidence_pct: int = 0


@dataclass
class AttentionShifted(Event):
    previous_track_id: Optional[int] = None
    track_id: Optional[int] = None


@dataclass
class StateChanged(Event):
    previous_state: str = ""
    new_state: str = ""
    reason: str = ""


@dataclass
class InteractionStarted(Event):
    track_id: int = 0
    name: str = ""


@dataclass
class UserCommandIntent(Event):
    intent: str = ""
    raw_text: str = ""


Handler = Callable[[Event], None]


class EventBus:
    """Thread-safe enough for single-writer (main thread) + drain on main thread."""

    def __init__(self, max_queue: int = 256):
        self._queue: Deque[Event] = deque(maxlen=max_queue)
        self._handlers: Dict[Type[Event], List[Handler]] = defaultdict(list)
        self._wildcard: List[Handler] = []

    def subscribe(self, event_type: Type[Event], handler: Handler):
        self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: Handler):
        self._wildcard.append(handler)

    def emit(self, event: Event):
        self._queue.append(event)

    def drain(self) -> List[Event]:
        events = list(self._queue)
        self._queue.clear()
        return events

    def dispatch(self, events: Optional[List[Event]] = None):
        batch = events if events is not None else self.drain()
        for event in batch:
            for handler in self._wildcard:
                handler(event)
            for cls, handlers in self._handlers.items():
                if isinstance(event, cls):
                    for h in handlers:
                        h(event)
