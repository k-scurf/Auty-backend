"""
Project paths — single source for config and local biometric data (gitignored).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# Repo root (parent of utils/)
PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = Path(os.environ.get("AUTY_DATA_DIR", PROJECT_ROOT / "data")).resolve()
CONFIG_DIR = Path(os.environ.get("AUTY_CONFIG_DIR", PROJECT_ROOT / "config")).resolve()

SETTINGS_EXAMPLE = CONFIG_DIR / "settings.example.json"
SETTINGS_PATH = Path(
    os.environ.get("AUTY_CONFIG", DATA_DIR / "settings.json")
).resolve()

FACE_DB_PATH = DATA_DIR / "face_db.pkl"
PROFILES_PATH = DATA_DIR / "profiles.json"
MEMORY_PATH = DATA_DIR / "memory.json"
CAPTURES_DIR = DATA_DIR / "captures"
LOG_PATH = DATA_DIR / "logs.txt"
PRESENCE_SESSIONS_PATH = DATA_DIR / "presence_sessions.json"
ATTENDANCE_LOG_PATH = DATA_DIR / "attendance_log.jsonl"
ATTENDANCE_NOTES_PATH = DATA_DIR / "attendance_notes.json"
SCHEDULES_PATH = DATA_DIR / "schedules.json"
CONSENT_LOG_PATH = DATA_DIR / "consent_log.json"
AUDIT_LOG_PATH = DATA_DIR / "audit_log.jsonl"

_LEGACY_ROOT_FILES = (
    ("face_db.pkl", FACE_DB_PATH),
    ("profiles.json", PROFILES_PATH),
    ("memory.json", MEMORY_PATH),
    ("settings.json", SETTINGS_PATH),
    ("logs.txt", LOG_PATH),
)


def ensure_directories():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def migrate_legacy_data() -> list[str]:
    """Copy runtime files from repo root into data/ if not already present."""
    ensure_directories()
    moved = []
    for name, dest in _LEGACY_ROOT_FILES:
        src = PROJECT_ROOT / name
        if not src.is_file() or dest.exists():
            continue
        shutil.copy2(src, dest)
        moved.append(name)
    legacy_captures = PROJECT_ROOT / "captures"
    if legacy_captures.is_dir():
        for item in legacy_captures.iterdir():
            if item.is_file():
                target = CAPTURES_DIR / item.name
                if not target.exists():
                    shutil.copy2(item, target)
        if any(legacy_captures.iterdir()):
            moved.append("captures/")
    if moved:
        print(
            "[Auty] Migrated local data into data/: "
            + ", ".join(moved)
            + " (root copies kept; you may delete them after verifying)."
        )
    return moved


def default_settings_path() -> Path:
    ensure_directories()
    if not SETTINGS_PATH.is_file() and SETTINGS_EXAMPLE.is_file():
        shutil.copy2(SETTINGS_EXAMPLE, SETTINGS_PATH)
    return SETTINGS_PATH
