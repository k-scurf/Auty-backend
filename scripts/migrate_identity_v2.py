#!/usr/bin/env python3
"""Migrate face_db.pkl + profiles.json into data/identities/ v2 layout."""

from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.settings_loader import load_settings
from utils.paths import FACE_DB_PATH, PROFILES_PATH
from vision.identity_store import IdentityStore


def main():
    settings = load_settings()
    store = IdentityStore(settings)

    if not FACE_DB_PATH.exists():
        print("No face_db.pkl — nothing to migrate.")
        return

    with open(FACE_DB_PATH, "rb") as f:
        raw = pickle.load(f)

    profiles = {}
    if PROFILES_PATH.exists():
        import json

        with open(PROFILES_PATH) as pf:
            profiles = json.load(pf)

    count = 0
    for name, value in raw.items():
        if store.find_by_name(name):
            continue
        if isinstance(value, list):
            embeddings = value
        else:
            embeddings = [value]
        prof = profiles.get(name, {})
        store.add_person(
            name,
            embeddings,
            image_path=prof.get("image"),
            profile=prof,
        )
        count += 1

    print(f"Migrated {count} identity record(s) to {store}")


if __name__ == "__main__":
    main()
