"""
Face embedding database (pickle) and profile metadata (JSON).
"""

import json
import os
import pickle

import recognition as rec
from utils.paths import CAPTURES_DIR, FACE_DB_PATH, PROFILES_PATH, ensure_directories

ensure_directories()
FACE_DB = str(FACE_DB_PATH)
PROFILE_DB = str(PROFILES_PATH)
CAPTURE_FOLDER = str(CAPTURES_DIR)


class FaceDatabase:
    def __init__(self, settings: dict):
        self.settings = settings
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

    def load(self):
        if not os.path.exists(FACE_DB):
            self.face_db = {}
            return self.face_db
        with open(FACE_DB, "rb") as f:
            self.face_db = self.normalize_face_db(pickle.load(f))
        return self.face_db

    def save(self):
        with open(FACE_DB, "wb") as f:
            pickle.dump(self.face_db, f)

    def reset(self):
        self.face_db = {}
        self.save()
        with open(PROFILE_DB, "w") as f:
            json.dump({}, f)
        self._profiles_cache = {}
        self._profiles_mtime = os.path.getmtime(PROFILE_DB)

    def add_embedding(self, name, embedding):
        if not name or not rec.is_embedding(embedding):
            return False
        samples = self.face_db.setdefault(name, [])
        samples.append(rec.l2_normalize(embedding))
        if len(samples) > self.max_embeddings:
            del samples[: len(samples) - self.max_embeddings]
        return True

    def embedding_is_new(self, name, embedding):
        samples = self.face_db.get(name, [])
        if not samples:
            return True
        best = max(rec.cosine_similarity(embedding, s) for s in samples)
        min_dist = float(self.settings.get("min_new_embedding_distance", 0.02))
        return (1.0 - best) >= min_dist

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

    def save_profile(self, name, profile):
        data = self.load_profiles()
        data[name] = profile
        with open(PROFILE_DB, "w") as f:
            json.dump(data, f, indent=4)
        self._profiles_cache = data
        self._profiles_mtime = os.path.getmtime(PROFILE_DB)

    @property
    def capture_folder(self):
        return CAPTURE_FOLDER
