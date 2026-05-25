"""Simple JSON-backed weekly employee schedules."""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from typing import Any, Dict, Optional

from utils.paths import SCHEDULES_PATH

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_TZ = "America/Chicago"


def empty_days() -> Dict[str, dict]:
    return {
        day: {"working": False, "start": None, "end": None}
        for day in DAYS
    }


def normalize_schedule(employee_id: str, data: Optional[dict]) -> dict:
    src = data or {}
    days_src = src.get("days") or {}
    days = empty_days()
    for day in DAYS:
        raw = days_src.get(day) or {}
        working = bool(raw.get("working"))
        days[day] = {
            "working": working,
            "start": str(raw.get("start") or "09:00") if working else None,
            "end": str(raw.get("end") or "17:00") if working else None,
        }
    return {
        "employee_id": str(src.get("employee_id") or employee_id),
        "name": str(src.get("name") or ""),
        "timezone": str(src.get("timezone") or DEFAULT_TZ),
        "days": days,
    }


class ScheduleStore:
    def __init__(self, path: str | os.PathLike[str] = SCHEDULES_PATH):
        self.path = str(path)
        self._lock = threading.Lock()

    def _load_all_unlocked(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "schedules": {}}

        schedules = raw.get("schedules", {})
        if isinstance(schedules, list):
            schedules = {
                str(s.get("employee_id") or s.get("name")): s
                for s in schedules
                if s.get("employee_id") or s.get("name")
            }
        if not isinstance(schedules, dict):
            schedules = {}
        return {"version": int(raw.get("version", 1)), "schedules": schedules}

    def _save_all_unlocked(self, data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = f"{self.path}.tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    def get(self, employee_id: str) -> Optional[dict]:
        key = str(employee_id)
        with self._lock:
            raw = self._load_all_unlocked()["schedules"].get(key)
            return normalize_schedule(key, raw) if raw else None

    def save(self, employee_id: str, schedule: dict) -> dict:
        key = str(employee_id)
        normalized = normalize_schedule(key, schedule)
        with self._lock:
            data = self._load_all_unlocked()
            data["schedules"][key] = deepcopy(normalized)
            self._save_all_unlocked(data)
        return normalized

    def all(self) -> Dict[str, dict]:
        with self._lock:
            schedules = self._load_all_unlocked()["schedules"]
            return {
                str(employee_id): normalize_schedule(str(employee_id), schedule)
                for employee_id, schedule in schedules.items()
            }
