"""
Identity-keyed office presence — IN/OUT state, sessions, and attendance logging.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Deque, Dict, List, Optional, Tuple

from utils.performance import DebouncedSaver


class PresenceStatus(str, Enum):
    IN = "IN"
    OUT = "OUT"


@dataclass
class PersonPresence:
    name: str
    status: PresenceStatus = PresenceStatus.OUT
    first_seen_time: float = 0.0
    last_seen_time: float = 0.0
    check_in_time: float = 0.0
    confirm_streak: int = 0
    last_confirm_at: float = 0.0
    last_check_in_at: float = 0.0
    confidence_history: Deque[float] = field(default_factory=deque)
    active_session_id: Optional[str] = None


@dataclass
class PresenceSession:
    session_id: str
    name: str
    check_in: float
    check_out: float = 0.0
    duration_sec: float = 0.0


@dataclass
class PresenceTransition:
    event: str  # CHECK_IN | CHECK_OUT
    name: str
    ts: float
    detail: str = ""
    confidence: float = 0.0


@dataclass
class PresencePersonSnapshot:
    name: str
    status: str
    since_ts: float
    last_seen_ts: float
    confidence_avg: Optional[float] = None


@dataclass
class PresenceActivitySnapshot:
    name: str
    last_seen_ts: float
    event: str


@dataclass
class PresenceSnapshot:
    in_office: List[PresencePersonSnapshot] = field(default_factory=list)
    recent_activity: List[PresenceActivitySnapshot] = field(default_factory=list)
    today_totals: Dict[str, float] = field(default_factory=dict)
    events_tail: List[PresenceActivitySnapshot] = field(default_factory=list)


def _today_start_ts(now: Optional[float] = None) -> float:
    now = now or time.time()
    dt = datetime.fromtimestamp(now)
    start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp()


def _format_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%I:%M %p").lstrip("0")


class PresenceTracker:
    def __init__(
        self,
        settings: dict,
        *,
        sessions_path: str,
        on_transition: Optional[Callable[[PresenceTransition], None]] = None,
    ):
        self.settings = settings
        self._on_transition = on_transition
        self._enabled = bool(settings.get("presence_enabled", True))
        self._confirm_frames = int(settings.get("presence_confirm_frames", 8))
        self._confirm_window = float(
            settings.get("presence_confirm_window_seconds", 3.0)
        )
        self._out_timeout = float(settings.get("presence_out_timeout_seconds", 180))
        self._checkin_cooldown = float(
            settings.get("presence_checkin_cooldown_seconds", 600)
        )
        self._min_score = float(
            settings.get(
                "presence_min_lock_score",
                settings.get("min_lock_score", 0.62),
            )
        )
        self._hist_size = int(settings.get("presence_confidence_history_size", 20))
        self._console_log = bool(settings.get("presence_console_log", True))
        self._console_interval = float(
            settings.get("presence_status_interval_seconds", 30)
        )
        self._recent_max = 20
        self._events_max = 50

        self._sessions_path = sessions_path
        self._people: Dict[str, PersonPresence] = {}
        self._recent_activity: Deque[PresenceActivitySnapshot] = deque(
            maxlen=self._recent_max
        )
        self._events_tail: Deque[PresenceActivitySnapshot] = deque(
            maxlen=self._events_max
        )
        self._closed_sessions: List[dict] = []
        self._today_totals: Dict[str, float] = {}
        self._lock = threading.RLock()
        self._last_console_at = 0.0
        self._saver = DebouncedSaver(self._persist_sessions, delay_seconds=5.0)
        self._load_sessions_file()

    def reset(self):
        with self._lock:
            self._people.clear()
            self._recent_activity.clear()
            self._events_tail.clear()

    def update(
        self, observations: Dict[str, float], now: Optional[float] = None
    ) -> List[PresenceTransition]:
        if not self._enabled:
            return []
        now = now or time.time()
        transitions: List[PresenceTransition] = []

        with self._lock:
            observed = {
                name: score
                for name, score in observations.items()
                if name and name != "UNKNOWN" and score >= self._min_score
            }

            for name, score in observed.items():
                person = self._people.setdefault(name, PersonPresence(name=name))
                if person.status == PresenceStatus.IN:
                    person.last_seen_time = now
                    person.confidence_history.append(score)
                    while len(person.confidence_history) > self._hist_size:
                        person.confidence_history.popleft()
                else:
                    self._process_out_observation(person, score, now, transitions)

            for name, person in list(self._people.items()):
                if person.status != PresenceStatus.IN:
                    continue
                if name in observed:
                    continue
                if (now - person.last_seen_time) >= self._out_timeout:
                    self._check_out(person, now, transitions)

            if self._console_log and (
                now - self._last_console_at >= self._console_interval
            ):
                self._print_status_locked(now)
                self._last_console_at = now

        for t in transitions:
            if self._on_transition:
                self._on_transition(t)
        return transitions

    def force_check_out(self, name: str) -> None:
        """Immediately mark a person as OUT without emitting a transition event.

        Used when the attendance tracker has already logged a CLOCK_OUT directly
        (kiosk clock-out path) so that subsequent presence updates see them as
        available for a fresh CHECK_IN next time they approach.
        """
        if not name or name == "UNKNOWN":
            return
        now = time.time()
        with self._lock:
            person = self._people.get(name)
            if person is None or person.status == PresenceStatus.OUT:
                return
            person.status = PresenceStatus.OUT
            person.confirm_streak = 0
            person.active_session_id = None

    def force_check_in(
        self, name: str, score: float, now: Optional[float] = None
    ) -> List[PresenceTransition]:
        """Immediate check-in when recognition locks (kiosk / fast path)."""
        if not self._enabled or not name or name == "UNKNOWN":
            return []
        now = now or time.time()
        transitions: List[PresenceTransition] = []
        with self._lock:
            person = self._people.setdefault(name, PersonPresence(name=name))
            if person.status == PresenceStatus.IN:
                person.last_seen_time = now
                person.confidence_history.append(score)
                while len(person.confidence_history) > self._hist_size:
                    person.confidence_history.popleft()
                return []
            if person.last_check_in_at and (
                now - person.last_check_in_at
            ) < self._checkin_cooldown:
                return []
            person.confidence_history.append(score)
            self._check_in(person, now, transitions)
        for t in transitions:
            if self._on_transition:
                self._on_transition(t)
        return transitions

    def _process_out_observation(
        self,
        person: PersonPresence,
        score: float,
        now: float,
        transitions: List[PresenceTransition],
    ):
        if person.last_confirm_at and (now - person.last_confirm_at) > self._confirm_window:
            person.confirm_streak = 0

        person.confirm_streak += 1
        person.last_confirm_at = now
        if person.first_seen_time <= 0:
            person.first_seen_time = now
        person.last_seen_time = now
        person.confidence_history.append(score)
        while len(person.confidence_history) > self._hist_size:
            person.confidence_history.popleft()

        if person.confirm_streak < self._confirm_frames:
            return

        if person.last_check_in_at and (now - person.last_check_in_at) < self._checkin_cooldown:
            person.confirm_streak = 0
            return

        self._check_in(person, now, transitions)

    def _check_in(
        self, person: PersonPresence, now: float, transitions: List[PresenceTransition]
    ):
        person.status = PresenceStatus.IN
        person.check_in_time = now
        person.first_seen_time = now
        person.last_seen_time = now
        person.last_check_in_at = now
        person.confirm_streak = 0
        session_id = str(uuid.uuid4())[:8]
        person.active_session_id = session_id

        detail = f"Since {_format_time(now)}"
        hist = person.confidence_history
        conf = float(sum(hist) / len(hist)) if hist else self._min_score
        transitions.append(
            PresenceTransition(
                event="CHECK_IN",
                name=person.name,
                ts=now,
                detail=detail,
                confidence=conf,
            )
        )
        act = PresenceActivitySnapshot(
            name=person.name, last_seen_ts=now, event="CHECK_IN"
        )
        self._events_tail.append(act)

    def _check_out(
        self, person: PersonPresence, now: float, transitions: List[PresenceTransition]
    ):
        person.status = PresenceStatus.OUT
        person.confirm_streak = 0
        duration = max(0.0, now - person.check_in_time) if person.check_in_time else 0.0
        session = PresenceSession(
            session_id=person.active_session_id or str(uuid.uuid4())[:8],
            name=person.name,
            check_in=person.check_in_time or now,
            check_out=now,
            duration_sec=duration,
        )
        person.active_session_id = None
        self._record_closed_session(session)

        detail = f"Last seen {_format_time(person.last_seen_time)}"
        hist = person.confidence_history
        conf = float(sum(hist) / len(hist)) if hist else self._min_score
        transitions.append(
            PresenceTransition(
                event="CHECK_OUT",
                name=person.name,
                ts=now,
                detail=detail,
                confidence=conf,
            )
        )
        act = PresenceActivitySnapshot(
            name=person.name, last_seen_ts=person.last_seen_time, event="CHECK_OUT"
        )
        self._recent_activity.appendleft(act)
        self._events_tail.append(act)

    def _record_closed_session(self, session: PresenceSession):
        entry = {
            "session_id": session.session_id,
            "name": session.name,
            "check_in": session.check_in,
            "check_out": session.check_out,
            "duration_sec": round(session.duration_sec, 1),
        }
        self._closed_sessions.append(entry)
        if session.check_out >= _today_start_ts():
            self._today_totals[session.name] = (
                self._today_totals.get(session.name, 0.0) + session.duration_sec
            )
        self._saver.mark_dirty()

    def snapshot(self) -> PresenceSnapshot:
        with self._lock:
            in_office: List[PresencePersonSnapshot] = []
            for person in self._people.values():
                if person.status != PresenceStatus.IN:
                    continue
                hist = person.confidence_history
                avg = sum(hist) / len(hist) if hist else None
                in_office.append(
                    PresencePersonSnapshot(
                        name=person.name,
                        status=PresenceStatus.IN.value,
                        since_ts=person.check_in_time,
                        last_seen_ts=person.last_seen_time,
                        confidence_avg=round(avg, 3) if avg is not None else None,
                    )
                )
            in_office.sort(key=lambda p: p.since_ts)

            recent = list(self._recent_activity)
            events = list(self._events_tail)[-20:]
            return PresenceSnapshot(
                in_office=in_office,
                recent_activity=recent,
                today_totals=dict(self._today_totals),
                events_tail=events,
            )

    def format_status_block(self, now: Optional[float] = None) -> str:
        snap = self.snapshot()
        lines = ["CURRENT OFFICE STATUS:"]
        if not snap.in_office:
            lines.append("  (no one checked in)")
        else:
            for p in snap.in_office:
                lines.append(
                    f"  - {p.name} | IN | Since {_format_time(p.since_ts)}"
                )
        lines.append("RECENT ACTIVITY:")
        if not snap.recent_activity:
            lines.append("  (none)")
        else:
            for a in snap.recent_activity[:10]:
                if a.event == "CHECK_OUT":
                    lines.append(
                        f"  - {a.name} | Last seen {_format_time(a.last_seen_ts)}"
                    )
                else:
                    lines.append(
                        f"  - {a.name} | {a.event} {_format_time(a.last_seen_ts)}"
                    )
        return "\n".join(lines)

    def _print_status_locked(self, now: float):
        print(f"\n[Auty Presence]\n{self.format_status_block(now)}\n")

    def _load_sessions_file(self):
        try:
            with open(self._sessions_path, "r") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        sessions = data.get("sessions", [])
        if not isinstance(sessions, list):
            return
        today_start = _today_start_ts()
        totals: Dict[str, float] = {}
        for s in sessions:
            if not isinstance(s, dict):
                continue
            co = float(s.get("check_out", 0) or 0)
            if co < today_start:
                continue
            name = str(s.get("name", ""))
            if not name:
                continue
            totals[name] = totals.get(name, 0.0) + float(s.get("duration_sec", 0) or 0)
        self._today_totals = totals
        self._closed_sessions = [
            s for s in sessions if isinstance(s, dict)
        ][-500:]

    def _persist_sessions(self):
        with self._lock:
            payload = {"sessions": self._closed_sessions[-500:]}
        parent = os.path.dirname(self._sessions_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self._sessions_path, "w") as f:
            json.dump(payload, f, indent=2)

    def flush(self, *, force: bool = False):
        self._saver.maybe_flush(force=force)


def presence_to_api_dict(snap: PresenceSnapshot) -> dict:
    """Serialize snapshot for Pydantic PresenceOut."""
    return {
        "in_office": [
            {
                "name": p.name,
                "status": p.status,
                "since_ts": p.since_ts,
                "last_seen_ts": p.last_seen_ts,
                "confidence_avg": p.confidence_avg,
            }
            for p in snap.in_office
        ],
        "recent_activity": [
            {
                "name": a.name,
                "last_seen_ts": a.last_seen_ts,
                "event": a.event,
            }
            for a in snap.recent_activity
        ],
        "today_totals": dict(snap.today_totals),
        "events_tail": [
            {
                "name": a.name,
                "last_seen_ts": a.last_seen_ts,
                "event": a.event,
            }
            for a in snap.events_tail
        ],
    }
