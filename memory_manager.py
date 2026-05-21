"""
Persistent social memory: visits, history, relationship scores.
"""

import json
import os
import time
from typing import Optional

MEMORY_FILE = "memory.json"


def _week_start_ts(now: Optional[float] = None) -> float:
    now = now or time.time()
    # Monday 00:00 local
    import datetime

    dt = datetime.datetime.fromtimestamp(now)
    start = dt - datetime.timedelta(days=dt.weekday())
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp()


class MemoryManager:
    def __init__(self, settings: dict):
        self.settings = settings
        self.path = settings.get("memory_file", MEMORY_FILE)
        self.history_limit = int(settings.get("memory_history_limit", 50))
        self._save_delay = float(settings.get("memory_save_delay_seconds", 5.0))
        self._dirty = False
        self._last_save = 0.0
        self.data = self._load()

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def reset(self):
        """Clear visit history and relationship data (fresh session)."""
        self.data = {}
        self._dirty = False
        self._last_save = time.time()
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({}, f, indent=2)

    def save(self, *, force: bool = False):
        now = time.time()
        if not force and not self._dirty:
            return
        if not force and (now - self._last_save) < self._save_delay:
            return
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)
        self._dirty = False
        self._last_save = now

    def _mark_dirty(self):
        self._dirty = True

    def ensure_person(self, name: str, profiles: dict):
        if not name or name == "UNKNOWN":
            return
        if name not in self.data:
            self.data[name] = {
                "visit_count": 0,
                "first_seen": time.time(),
                "last_seen": 0,
                "weekly_visits": 0,
                "week_anchor": _week_start_ts(),
                "relationship_score": 0.5,
                "preferred_greeting": None,
                "history": [],
            }
            self._bump_relationship_from_profile(name, profiles)
            self.save(force=True)

    def _bump_relationship_from_profile(self, name: str, profiles: dict):
        prof = profiles.get(name, {})
        status = str(prof.get("status", "")).upper()
        entry = self.data.get(name)
        if not entry:
            return
        if "OWNER" in status:
            entry["relationship_score"] = max(float(entry.get("relationship_score", 0.5)), 0.9)
        elif status:
            entry["relationship_score"] = max(float(entry.get("relationship_score", 0.5)), 0.6)

    def record_sighting(self, name: str, event: str, mood: str = "", profiles: dict = None):
        if not name or name == "UNKNOWN":
            name = "UNKNOWN"
        profiles = profiles or {}
        now = time.time()
        entry = self.data.setdefault(
            name,
            {
                "visit_count": 0,
                "first_seen": now,
                "last_seen": 0,
                "weekly_visits": 0,
                "week_anchor": _week_start_ts(now),
                "relationship_score": 0.3 if name == "UNKNOWN" else 0.5,
                "preferred_greeting": None,
                "history": [],
            },
        )
        if _week_start_ts(now) > entry.get("week_anchor", 0):
            entry["weekly_visits"] = 0
            entry["week_anchor"] = _week_start_ts(now)

        entry["visit_count"] = int(entry.get("visit_count", 0)) + 1
        entry["weekly_visits"] = int(entry.get("weekly_visits", 0)) + 1
        entry["last_seen"] = now
        if profiles and name != "UNKNOWN":
            self._bump_relationship_from_profile(name, profiles)
            entry["relationship_score"] = min(
                1.0, float(entry.get("relationship_score", 0.5)) + 0.02
            )

        hist = entry.setdefault("history", [])
        # Avoid duplicate back-to-back identical log lines (same second, same event).
        if hist:
            last = hist[-1]
            if (
                last.get("event") == event
                and (now - float(last.get("ts", 0))) < 2.0
            ):
                entry["last_seen"] = now
                self._mark_dirty()
                return

        hist.append({"ts": now, "event": event, "mood": mood})
        if len(hist) > self.history_limit:
            entry["history"] = hist[-self.history_limit :]
        self._mark_dirty()
        if (now - self._last_save) >= self._save_delay:
            self.save()

    def get_relationship_tier(self, name: str, profiles: dict) -> str:
        if name == "UNKNOWN":
            return "UNKNOWN"
        prof = profiles.get(name, {})
        status = str(prof.get("status", "")).strip().upper()
        if "OWNER" in status:
            return "OWNER"
        if status:
            return status if status in ("FRIEND", "OWNER") else "FRIEND"
        score = float(self.data.get(name, {}).get("relationship_score", 0.5))
        if score >= float(self.settings.get("relationship_greet_threshold", 0.7)):
            return "FRIEND"
        return "FRIEND"

    def get_memory_line(self, name: str) -> str:
        if name == "UNKNOWN":
            return ""
        entry = self.data.get(name)
        if not entry:
            return ""
        weekly = int(entry.get("weekly_visits", 0))
        total = int(entry.get("visit_count", 0))
        if weekly > 1:
            return f"You've appeared {weekly} times this week."
        if total > 1:
            return f"I've seen you {total} times."
        return ""

    def get_relationship_score(self, name: str) -> float:
        if name == "UNKNOWN":
            return 0.0
        return float(self.data.get(name, {}).get("relationship_score", 0.5))
