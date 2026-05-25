"""
Unified memory facade — profiles, embeddings DB, and social visit history.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import database as db_mod
from memory_manager import MemoryManager
from utils.performance import DebouncedSaver


class Memory:
    """Single entry point for persistence used by the response engine."""

    def __init__(self, settings: dict, face_database: db_mod.FaceDatabase):
        self.settings = settings
        self.db = face_database
        self.social = MemoryManager(settings)
        delay = float(settings.get("memory_save_delay_seconds", 5.0))
        self._saver = DebouncedSaver(self._persist, delay_seconds=delay)

    @property
    def face_db(self) -> dict:
        return self.db.face_db

    def load_profiles(self) -> dict:
        return self.db.load_profiles()

    def save_profiles(self):
        pass  # profiles saved via save_profile only

    def _persist(self):
        self.social.save(force=True)
        self.db.save()

    def flush(self, *, force: bool = False):
        if force:
            self._persist()
        else:
            self._saver.mark_dirty()
            self._saver.maybe_flush()

    def get_person(self, name: str) -> Dict[str, Any]:
        profiles = self.load_profiles()
        prof = dict(profiles.get(name, {}))
        social = self.social.data.get(name, {})
        prof["visit_count"] = int(social.get("visit_count", 0))
        prof["last_seen"] = social.get("last_seen", 0)
        prof["relationship_score"] = float(social.get("relationship_score", 0.5))
        return prof

    def record_event(self, name: str, event: str, mood: str = "", profiles: dict = None):
        profiles = profiles or self.load_profiles()
        self.social.record_sighting(name, event, mood, profiles)

    def ensure_person(self, name: str, profiles: dict = None):
        profiles = profiles or self.load_profiles()
        self.social.ensure_person(name, profiles)

    def get_visit_summary(self, name: str) -> str:
        return self.social.get_memory_line(name)

    def get_memory_line(self, name: str) -> str:
        return self.get_visit_summary(name)

    def reset(self):
        """Clear social memory file and in-memory visit history."""
        self.social.reset()

    def save(self, *, force: bool = False):
        if force:
            self._persist()
        else:
            self._saver.mark_dirty()
            self._saver.maybe_flush()

    def get_relationship_tier(self, name: str, profiles: dict) -> str:
        return self.social.get_relationship_tier(name, profiles)

    def save_profile(self, name: str, profile: dict):
        self.db.save_profile(name, profile)

    def add_embedding(self, name: str, embedding) -> bool:
        return self.db.add_embedding(name, embedding)
