"""
Payroll CSV export — Gusto, ADP Run, and Square Payroll formats.

All three formats consume paired CLOCK_IN / CLOCK_OUT events from the
AttendanceTracker log.  Unpaired CLOCK_IN events (employee still clocked in)
are excluded; they appear in the "active" list instead.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from attendance_tracker import AttendanceTracker

SUPPORTED_FORMATS = ("gusto", "adp", "square")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_tz(tz_name: str):
    """Return a ZoneInfo for tz_name, falling back to UTC on invalid names."""
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, Exception):
        return timezone.utc


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse YYYY-MM-DD as UTC midnight (kept for internal use only)."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _midnight_ts(date_str: str, tz, offset_days: int = 0) -> Optional[float]:
    """Return the Unix timestamp for midnight of *date_str* in *tz*, plus *offset_days*.

    Parses the date boundary in the user's local timezone so that, e.g.,
    "2025-01-15" with tz=America/Chicago means Jan 15 at midnight local time,
    not UTC midnight (which would be 6 hours earlier).
    """
    if not date_str:
        return None
    try:
        y, m, d = (int(x) for x in date_str.split("-"))
        return (datetime(y, m, d, tzinfo=tz) + timedelta(days=offset_days)).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def _ts_to_date(ts: float, tz=timezone.utc) -> str:
    return datetime.fromtimestamp(ts, tz=tz).strftime("%Y-%m-%d")


def _ts_to_hhmm(ts: float, tz=timezone.utc) -> str:
    return datetime.fromtimestamp(ts, tz=tz).strftime("%H:%M")


def _decimal_hours(seconds: float) -> float:
    return round(seconds / 3600, 2)


def _pair_events(events: List[dict], tz=timezone.utc) -> List[dict]:
    """
    Pair CLOCK_IN and CLOCK_OUT events per employee.
    Returns a list of shift dicts with keys:
      name, employee_id, date, clock_in_ts, clock_out_ts, duration_seconds, notes

    A second CLOCK_IN before a CLOCK_OUT (e.g. after a server restart) does NOT
    overwrite the first — the first clock-in is preserved until its matching
    CLOCK_OUT arrives.  This prevents data loss when the server restarts while
    an employee is mid-shift.
    """
    by_employee: Dict[str, List[dict]] = {}
    for ev in sorted(events, key=lambda e: e["timestamp_ts"]):
        by_employee.setdefault(ev["name"], []).append(ev)

    shifts = []
    for name, evs in by_employee.items():
        pending_in: Optional[dict] = None
        for ev in evs:
            if ev["event"] == "CLOCK_IN":
                if pending_in is None:
                    pending_in = ev
                # else: ignore duplicate CLOCK_IN — keeps the first one
            elif ev["event"] == "CLOCK_OUT" and pending_in is not None:
                duration = ev["timestamp_ts"] - pending_in["timestamp_ts"]
                shifts.append(
                    {
                        "name": name,
                        "employee_id": ev.get("employee_id", name),
                        "date": _ts_to_date(pending_in["timestamp_ts"], tz),
                        "clock_in_ts": pending_in["timestamp_ts"],
                        "clock_out_ts": ev["timestamp_ts"],
                        "duration_seconds": max(0.0, duration),
                        "notes": "",
                    }
                )
                pending_in = None
    return shifts


def _get_events(
    tracker: AttendanceTracker,
    start_date: str,
    end_date: str,
    location_id: Optional[str],
    tz=timezone.utc,
) -> List[dict]:
    """Fetch raw events.  Date boundaries are interpreted as midnight in *tz*
    (not UTC midnight) so that a shift at 11 pm local time is never cut off by
    a UTC-day rollover."""
    return tracker.get_events(
        start_ts=_midnight_ts(start_date, tz),
        end_ts=_midnight_ts(end_date, tz, offset_days=1),  # exclusive: midnight of next day
        location_id=location_id,
    )


# ---------------------------------------------------------------------------
# Format builders
# ---------------------------------------------------------------------------

def _gusto_csv(shifts: List[dict], tz=timezone.utc) -> str:
    """
    Gusto CSV format:
    Employee Name, Employee ID, Date, Clock In, Clock Out, Regular Hours, Notes
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["Employee Name", "Employee ID", "Date", "Clock In", "Clock Out", "Regular Hours", "Notes"]
    )
    for s in shifts:
        writer.writerow(
            [
                s["name"],
                s["employee_id"],
                s["date"],
                _ts_to_hhmm(s["clock_in_ts"], tz),
                _ts_to_hhmm(s["clock_out_ts"], tz),
                _decimal_hours(s["duration_seconds"]),
                s.get("notes", ""),
            ]
        )
    return buf.getvalue()


def _adp_csv(shifts: List[dict], tz=timezone.utc) -> str:
    """
    ADP Run CSV format:
    File Number, Temp Dept, Hours Worked, Earnings Code
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["File Number", "Temp Dept", "Hours Worked", "Earnings Code"])
    for s in shifts:
        writer.writerow(
            [
                s["employee_id"],
                "",
                _decimal_hours(s["duration_seconds"]),
                "REG",
            ]
        )
    return buf.getvalue()


def _square_csv(shifts: List[dict], tz=timezone.utc) -> str:
    """
    Square Payroll CSV format:
    Employee Name, Date, Start Time, End Time, Total Hours
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Employee Name", "Date", "Start Time", "End Time", "Total Hours"])
    for s in shifts:
        writer.writerow(
            [
                s["name"],
                s["date"],
                _ts_to_hhmm(s["clock_in_ts"], tz),
                _ts_to_hhmm(s["clock_out_ts"], tz),
                _decimal_hours(s["duration_seconds"]),
            ]
        )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_export_csv(
    tracker: AttendanceTracker,
    format: str,
    start_date: str,
    end_date: str,
    location_id: Optional[str] = None,
    tz_name: str = "UTC",
) -> str:
    """Generate a payroll CSV string for the given format and date range.

    Clock-in/out times are formatted in *tz_name* (IANA timezone, e.g.
    "America/Chicago").  Defaults to UTC if the name is invalid.
    """
    fmt = format.lower().strip()
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported format: {format!r}. Use: {SUPPORTED_FORMATS}")

    tz = _resolve_tz(tz_name)
    events = _get_events(tracker, start_date, end_date, location_id, tz)
    shifts = _pair_events(events, tz)

    if fmt == "gusto":
        return _gusto_csv(shifts, tz)
    elif fmt == "adp":
        return _adp_csv(shifts, tz)
    elif fmt == "square":
        return _square_csv(shifts, tz)
    raise ValueError(f"Unsupported format: {fmt}")


def compute_preview_from_events(
    events: List[dict],
    format: str,
    start_date: str,
    end_date: str,
    location_id: Optional[str] = None,
    tz_name: str = "UTC",
) -> dict:
    """Preview summary from a pre-fetched event list."""
    tz = _resolve_tz(tz_name)
    filtered = _filter_events(events, start_date, end_date, location_id, tz)
    shifts = _pair_events(filtered, tz)
    total_seconds = sum(s["duration_seconds"] for s in shifts)
    employee_names = {s["name"] for s in shifts}
    return {
        "row_count": len(shifts),
        "total_hours": _decimal_hours(total_seconds),
        "employee_count": len(employee_names),
        "format": format,
        "start_date": start_date,
        "end_date": end_date,
    }


def build_export_csv_from_events(
    events: List[dict],
    format: str,
    start_date: str,
    end_date: str,
    location_id: Optional[str] = None,
    tz_name: str = "UTC",
) -> str:
    fmt = format.lower().strip()
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported format: {format!r}. Use: {SUPPORTED_FORMATS}")
    tz = _resolve_tz(tz_name)
    filtered = _filter_events(events, start_date, end_date, location_id, tz)
    shifts = _pair_events(filtered, tz)
    if fmt == "gusto":
        return _gusto_csv(shifts, tz)
    if fmt == "adp":
        return _adp_csv(shifts, tz)
    if fmt == "square":
        return _square_csv(shifts, tz)
    raise ValueError(f"Unsupported format: {fmt}")


def _filter_events(
    events: List[dict],
    start_date: str,
    end_date: str,
    location_id: Optional[str],
    tz,
) -> List[dict]:
    start_ts = _midnight_ts(start_date, tz)
    end_ts = _midnight_ts(end_date, tz, offset_days=1)
    out = []
    for ev in events:
        ts = ev.get("timestamp_ts", 0)
        if start_ts is not None and ts < start_ts:
            continue
        if end_ts is not None and ts > end_ts:
            continue
        if location_id and ev.get("location_id") != location_id:
            continue
        out.append(ev)
    return out


def compute_preview(
    tracker: AttendanceTracker,
    format: str,
    start_date: str,
    end_date: str,
    location_id: Optional[str] = None,
    tz_name: str = "UTC",
) -> dict:
    """Return a preview summary without generating the full CSV."""
    tz = _resolve_tz(tz_name)
    events = _get_events(tracker, start_date, end_date, location_id, tz)
    return compute_preview_from_events(
        events, format, start_date, end_date, location_id, tz_name=tz_name
    )


