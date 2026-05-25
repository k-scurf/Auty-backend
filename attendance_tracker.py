"""
Payroll-grade clock-in / clock-out attendance tracker.

Each recognition event (confidence >= MIN_CONFIDENCE) toggles the employee's
state between CLOCK_IN and CLOCK_OUT and appends an immutable record to
data/attendance_log.jsonl.  Manager notes are stored separately in
data/attendance_notes.json so the original records are never modified.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional

from utils.time_utils import utc_now_iso as _utc_now_iso

# Minimum recognition confidence to trigger a clock event.
MIN_CONFIDENCE: float = 0.75

# Consecutive unrecognized attempts before a manager alert is triggered.
FAIL_STREAK_THRESHOLD: int = 3


def _utc_ts() -> float:
    return time.time()


@dataclass
class AttendanceEvent:
    id: str
    employee_id: str
    name: str
    event: str  # CLOCK_IN | CLOCK_OUT
    timestamp_utc: str
    timestamp_ts: float
    location_id: str
    confidence: float
    device_id: str
    snapshot_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "employee_id": self.employee_id,
            "name": self.name,
            "event": self.event,
            "timestamp_utc": self.timestamp_utc,
            "timestamp_ts": self.timestamp_ts,
            "location_id": self.location_id,
            "confidence": round(self.confidence, 4),
            "device_id": self.device_id,
            "snapshot_path": self.snapshot_path,
        }


@dataclass
class ActiveEmployee:
    employee_id: str
    name: str
    clock_in_ts: float
    clock_in_utc: str
    location_id: str
    confidence: float
    last_seen_ts: float

    @property
    def duration_seconds(self) -> float:
        return max(0.0, _utc_ts() - self.clock_in_ts)


@dataclass
class AttendanceAlert:
    type: str  # fail_streak | missing_clock_out
    name: str
    ts: float
    detail: str = ""


@dataclass
class _EmployeeState:
    name: str
    employee_id: str
    clocked_in: bool = False
    last_clock_in_ts: float = 0.0
    last_clock_in_utc: str = ""
    last_clock_in_event_id: str = ""
    last_seen_ts: float = 0.0
    fail_streak: int = 0
    last_fail_streak_alert_ts: float = 0.0


class AttendanceTracker:
    """
    Thread-safe attendance tracker.  Call ``record_recognition`` when the
    recognition pipeline confirms a face above the confidence threshold, and
    ``record_fail`` when a face is present but not recognized.
    """

    def __init__(
        self,
        *,
        log_path: str,
        notes_path: str,
        location_id: str = "main",
        device_id: str = "default",
        min_confidence: float = MIN_CONFIDENCE,
        provisional_prefix: str = "Guest",
        on_alert: Optional[Callable[[AttendanceAlert], None]] = None,
    ):
        self._log_path = log_path
        self._notes_path = notes_path
        self._location_id = location_id
        self._device_id = device_id
        self._min_confidence = float(min_confidence)
        # Names that start with this prefix are provisional auto-enrollments.
        # They are excluded from clock-in state, active list, and log replay.
        self._provisional_prefix = str(provisional_prefix) if provisional_prefix else ""
        self._on_alert = on_alert

        self._lock = threading.Lock()
        self._states: Dict[str, _EmployeeState] = {}
        self._active: Dict[str, ActiveEmployee] = {}
        self._recent_events: Deque[AttendanceEvent] = deque(maxlen=100)
        self._alerts: Deque[AttendanceAlert] = deque(maxlen=50)

        log_dir = os.path.dirname(log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        notes_dir = os.path.dirname(notes_path)
        if notes_dir:
            os.makedirs(notes_dir, exist_ok=True)
        self._load_state_from_log()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_provisional(self, name: str) -> bool:
        """Return True if *name* looks like an unconfirmed auto-enrollment."""
        return bool(self._provisional_prefix and name.startswith(self._provisional_prefix))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_recognition(
        self,
        name: str,
        employee_id: str,
        confidence: float,
        *,
        save_snapshot: bool = False,
    ) -> Optional[AttendanceEvent]:
        """
        Called when the recognition pipeline locks onto a known employee with
        confidence >= MIN_CONFIDENCE.  Returns the AttendanceEvent or None if
        the confidence gate is not met.
        """
        if confidence < self._min_confidence:
            return None
        if self._is_provisional(name):
            return None

        with self._lock:
            state = self._states.setdefault(
                name, _EmployeeState(name=name, employee_id=employee_id)
            )
            state.employee_id = employee_id
            state.last_seen_ts = _utc_ts()
            state.fail_streak = 0

            event_type = "CLOCK_IN" if not state.clocked_in else "CLOCK_OUT"
            event = self._build_event(name, employee_id, event_type, confidence)
            self._append_log(event)
            self._recent_events.append(event)

            if event_type == "CLOCK_IN":
                state.clocked_in = True
                state.last_clock_in_ts = event.timestamp_ts
                state.last_clock_in_utc = event.timestamp_utc
                state.last_clock_in_event_id = event.id
                self._active[name] = ActiveEmployee(
                    employee_id=employee_id,
                    name=name,
                    clock_in_ts=event.timestamp_ts,
                    clock_in_utc=event.timestamp_utc,
                    location_id=event.location_id,
                    confidence=confidence,
                    last_seen_ts=event.timestamp_ts,
                )
            else:
                state.clocked_in = False
                self._active.pop(name, None)

        return event

    def record_fail(self, track_id: int = -1) -> Optional[AttendanceAlert]:
        """
        Called when a face is detected but not recognized (or confidence below
        threshold).  Returns an AttendanceAlert if the fail streak threshold is
        reached, so callers can notify the manager dashboard.
        """
        key = f"__unrecognized_{track_id}__"
        with self._lock:
            now = _utc_ts()
            state = self._states.setdefault(
                key, _EmployeeState(name="UNRECOGNIZED", employee_id="")
            )
            state.fail_streak += 1
            state.last_seen_ts = now

            if state.fail_streak >= FAIL_STREAK_THRESHOLD:
                if now - state.last_fail_streak_alert_ts > 30:
                    alert = AttendanceAlert(
                        type="fail_streak",
                        name="Unrecognized face",
                        ts=now,
                        detail=f"{state.fail_streak} consecutive unrecognized attempts",
                    )
                    state.fail_streak = 0
                    state.last_fail_streak_alert_ts = now
                    self._alerts.append(alert)
                    if self._on_alert:
                        self._on_alert(alert)
                    return alert
        return None

    def reset(self) -> None:
        """Clear all in-memory state (active employees, per-person clock state, events, alerts)."""
        with self._lock:
            self._states.clear()
            self._active.clear()
            self._recent_events.clear()
            self._alerts.clear()

    def is_clocked_in(self, name: str) -> bool:
        """Return True if the named employee is currently clocked in."""
        with self._lock:
            state = self._states.get(name)
            return state.clocked_in if state else False

    def get_active(self) -> List[ActiveEmployee]:
        """Return named employees currently clocked in, sorted by clock-in time.
        Provisional/guest identities are excluded."""
        with self._lock:
            return sorted(
                (e for e in self._active.values() if not self._is_provisional(e.name)),
                key=lambda e: e.clock_in_ts,
            )

    def get_events(
        self,
        *,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        employee_name: Optional[str] = None,
        location_id: Optional[str] = None,
    ) -> List[dict]:
        """Read events from the append-only log with optional filters."""
        events: List[dict] = []
        try:
            f_handle = open(self._log_path, "r")
        except OSError:
            return events
        with f_handle as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = ev.get("timestamp_ts", 0)
                if start_ts is not None and ts < start_ts:
                    continue
                if end_ts is not None and ts > end_ts:
                    continue
                if employee_name and ev.get("name") != employee_name:
                    continue
                if location_id and ev.get("location_id") != location_id:
                    continue
                events.append(ev)
        return events

    def add_note(self, event_id: str, note: str, manager: str = "manager") -> bool:
        """Append a manager note for a specific event (never edits the original)."""
        known_ids = {ev.get("id") for ev in self.get_events()}
        if event_id not in known_ids:
            return False
        notes = self._load_notes()
        if event_id not in notes:
            notes[event_id] = []
        notes[event_id].append(
            {
                "ts": _utc_now_iso(),
                "manager": manager,
                "note": note,
            }
        )
        self._save_notes(notes)
        return True

    def get_notes(self, event_id: str) -> List[dict]:
        notes = self._load_notes()
        return notes.get(event_id, [])

    def get_alerts(self) -> List[AttendanceAlert]:
        with self._lock:
            return list(self._alerts)

    def get_recent_events(self, limit: int = 20) -> List[AttendanceEvent]:
        with self._lock:
            n = max(0, int(limit))
            events = list(self._recent_events)
            return events[-n:] if n else []

    def snapshot_dict(self) -> dict:
        """Serialize current state for the WebSocket FrameSnapshot."""
        active = self.get_active()
        return {
            "clocked_in": [
                {
                    "employee_id": e.employee_id,
                    "name": e.name,
                    "clock_in_ts": e.clock_in_ts,
                    "clock_in_utc": e.clock_in_utc,
                    "duration_seconds": round(e.duration_seconds),
                    "location_id": e.location_id,
                }
                for e in active
            ],
            "recent_events": [
                e.to_dict() for e in self.get_recent_events(10)
            ],
            "alerts": [
                {"type": a.type, "name": a.name, "ts": a.ts, "detail": a.detail}
                for a in self.get_alerts()[-5:]
            ],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_state_from_log(self) -> None:
        """Reconstruct in-memory clock state from the on-disk log.

        Called once on startup so that a server restart does not lose knowledge
        of who was already clocked in — preventing spurious duplicate CLOCK_INs
        on the next face scan after a restart.
        """
        try:
            events = self.get_events()
        except Exception:
            return
        by_employee: Dict[str, List[dict]] = {}
        for ev in sorted(events, key=lambda e: e.get("timestamp_ts", 0)):
            name = ev.get("name", "")
            if not name or name.startswith("__unrecognized_"):
                continue
            if self._is_provisional(name):
                continue  # skip ghost clock-ins from unconfirmed auto-enrollments
            by_employee.setdefault(name, []).append(ev)

        with self._lock:
            for name, evs in by_employee.items():
                last = evs[-1]
                state = self._states.setdefault(
                    name, _EmployeeState(name=name, employee_id=last.get("employee_id", name))
                )
                state.employee_id = last.get("employee_id", name)
                state.last_seen_ts = last.get("timestamp_ts", 0.0)
                if last.get("event") == "CLOCK_IN":
                    state.clocked_in = True
                    state.last_clock_in_ts = last.get("timestamp_ts", 0.0)
                    state.last_clock_in_utc = last.get("timestamp_utc", "")
                    state.last_clock_in_event_id = last.get("id", "")
                    self._active[name] = ActiveEmployee(
                        employee_id=state.employee_id,
                        name=name,
                        clock_in_ts=state.last_clock_in_ts,
                        clock_in_utc=state.last_clock_in_utc,
                        location_id=last.get("location_id", self._location_id),
                        confidence=last.get("confidence", 0.0),
                        last_seen_ts=state.last_seen_ts,
                    )
                else:
                    state.clocked_in = False
                    self._active.pop(name, None)

    def _build_event(
        self, name: str, employee_id: str, event_type: str, confidence: float
    ) -> AttendanceEvent:
        now_ts = _utc_ts()
        now_iso = _utc_now_iso()
        return AttendanceEvent(
            id=str(uuid.uuid4()),
            employee_id=employee_id,
            name=name,
            event=event_type,
            timestamp_utc=now_iso,
            timestamp_ts=now_ts,
            location_id=self._location_id,
            confidence=confidence,
            device_id=self._device_id,
        )

    def _append_log(self, event: AttendanceEvent):
        with open(self._log_path, "a") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    def _load_notes(self) -> dict:
        try:
            with open(self._notes_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_notes(self, notes: dict):
        with open(self._notes_path, "w") as f:
            json.dump(notes, f, indent=2)
