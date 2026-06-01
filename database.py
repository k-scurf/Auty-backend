"""
Face database — IdentityStore v2 with legacy pickle migration.
"""

import json
import os

import recognition as rec
from utils.paths import CAPTURES_DIR, FACE_DB_PATH, PROFILES_PATH, ensure_directories
from vision.identity_store import IdentityStore

ensure_directories()
FACE_DB = str(FACE_DB_PATH)
PROFILE_DB = str(PROFILES_PATH)
CAPTURE_FOLDER = str(CAPTURES_DIR)


class FaceDatabase:
    def __init__(self, settings: dict):
        self.settings = settings
        self.store = IdentityStore(settings)
        self.face_db = {}
        self.max_embeddings = int(settings.get("max_embeddings_per_person", 25))
        self._profiles_cache = None
        self._profiles_mtime = 0.0
        os.makedirs(CAPTURE_FOLDER, exist_ok=True)
        if not os.path.exists(PROFILE_DB):
            with open(PROFILE_DB, "w") as f:
                json.dump({}, f)

    def configure(self):
        rec.configure(self.settings)

    def normalize_face_db(self, raw_db):
        if not isinstance(raw_db, dict):
            return {}
        normalized = {}
        for name, value in raw_db.items():
            if rec.is_embedding(value):
                normalized[str(name)] = [rec.l2_normalize(value)]
                continue
            if isinstance(value, (list, tuple)):
                samples = [
                    rec.l2_normalize(s) for s in value if rec.is_embedding(s)
                ]
                if samples:
                    normalized[str(name)] = samples[: self.max_embeddings]
        return normalized

    def _migrate_pickle_if_needed(self):
        # Fix #3: pickle.load() is arbitrary code execution. This migration path
        # runs at most once — we delete the .pkl file after a successful import
        # so the unsafe load path is never exercised again.
        if self.face_db:
            return
        if not os.path.exists(FACE_DB):
            return
        try:
            import pickle  # imported locally so normal code paths never use it
            with open(FACE_DB, "rb") as f:
                raw = pickle.load(f)
            legacy = self.normalize_face_db(raw)
            profiles = self.load_profiles()
            for name, embeddings in legacy.items():
                prof = profiles.get(name, {})
                image = prof.get("image")
                self.store.add_person(
                    name,
                    embeddings,
                    image_path=image,
                    profile=prof,
                )
            self.face_db = self.store.build_face_db()
            print(f"[database] Migrated {len(legacy)} profile(s) to identity v2")
            # Delete the pickle so it can never be loaded again
            try:
                os.remove(FACE_DB)
                print("[database] Removed legacy face_db.pkl after migration")
            except OSError:
                pass
        except (OSError, EOFError, ValueError) as exc:
            print(f"[database] Pickle migration skipped: {exc}")
        except Exception as exc:
            # Catch pickle.UnpicklingError (and any other deserialization error)
            # without importing pickle at module level.
            print(f"[database] Pickle migration skipped: {exc}")

    def load(self):
        self.face_db = self.store.load()
        self._migrate_pickle_if_needed()
        if not self.face_db:
            self.face_db = self.store.build_face_db()
        return self.face_db

    def save(self):
        # Fix #3: IdentityStore already persists embeddings as JSON in data/identities/.
        # No secondary pickle file is needed or written here.
        self.face_db = self.store.build_face_db()

    def reset(self, *, clear_captures: bool = True):
        self.store.reset(clear_captures=clear_captures)
        self.face_db = {}
        # Remove any leftover legacy pickle file
        if os.path.exists(FACE_DB):
            try:
                os.remove(FACE_DB)
            except OSError:
                pass
        with open(PROFILE_DB, "w") as f:
            json.dump({}, f)
        self._profiles_cache = {}
        self._profiles_mtime = os.path.getmtime(PROFILE_DB)
        if clear_captures and os.path.isdir(CAPTURE_FOLDER):
            for fname in os.listdir(CAPTURE_FOLDER):
                if fname.lower().endswith((".jpg", ".jpeg", ".png")):
                    try:
                        os.remove(os.path.join(CAPTURE_FOLDER, fname))
                    except OSError:
                        pass

    def add_embedding(self, name, embedding):
        if not name or not rec.is_embedding(embedding):
            return False
        self.store.add_embedding(name, embedding)
        self.face_db = self.store.build_face_db()
        return True

    def embedding_is_new(self, name, embedding):
        return self.store.embedding_is_new(name, embedding)

    def load_profiles(self):
        if not os.path.exists(PROFILE_DB):
            return {}
        mtime = os.path.getmtime(PROFILE_DB)
        if self._profiles_cache is not None and mtime == self._profiles_mtime:
            return self._profiles_cache
        with open(PROFILE_DB, "r") as f:
            data = json.load(f)
        self._profiles_cache = data
        self._profiles_mtime = mtime
        return data

    def get_profile(self, name):
        return self.load_profiles().get(name)

    def get_profile_by_id(self, rec_id: str):
        for rec in self.store._records.values():
            if rec.id == rec_id:
                meta = rec.metadata or {}
                return {
                    "id": rec.id,
                    "name": rec.name,
                    "age": meta.get("age", ""),
                    "status": meta.get("status", ""),
                    "image": rec.image_paths[0] if rec.image_paths else None,
                    "enrolled_at": rec.enrolled_at,
                }
        return None

    def delete_profile(self, name: str = None, rec_id: str = None) -> bool:
        if rec_id:
            rec = self.store._records.get(rec_id)
            if rec:
                name = rec.name
            self.store.delete(rec_id)
        elif name:
            rec = self.store.find_by_name(name)
            if rec:
                self.store.delete(rec.id)
        else:
            return False
        data = self.load_profiles()
        if name and name in data:
            del data[name]
            with open(PROFILE_DB, "w") as f:
                json.dump(data, f, indent=4)
            self._profiles_cache = data
        self.face_db = self.store.build_face_db()
        self.save()
        return True

    def rename_profile(self, old_name: str, new_name: str) -> bool:
        old_name = old_name.strip()
        new_name = new_name.strip()
        if not old_name or not new_name or old_name.lower() == new_name.lower():
            return False
        rec = self.store.rename_person(old_name, new_name)
        if rec is None:
            return False
        data = self.load_profiles()
        prof = data.pop(old_name, None) or self.get_profile(old_name) or {}
        prof["name"] = new_name
        data[new_name] = prof
        with open(PROFILE_DB, "w") as f:
            json.dump(data, f, indent=4)
        self._profiles_cache = data
        self._profiles_mtime = os.path.getmtime(PROFILE_DB)
        self.face_db = self.store.build_face_db()
        self.save()
        return True

    def save_profile(self, name, profile):
        data = self.load_profiles()
        data[name] = profile
        with open(PROFILE_DB, "w") as f:
            json.dump(data, f, indent=4)
        self._profiles_cache = data
        self._profiles_mtime = os.path.getmtime(PROFILE_DB)
        rec_meta = self.store.find_by_name(name)
        if rec_meta:
            rec_meta.metadata = profile
            self.store.save_record(rec_meta)
