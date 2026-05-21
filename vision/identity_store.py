"""Identity database v2 — UUID records with master embeddings."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np

from utils.paths import DATA_DIR, ensure_directories
from vision.gallery import rebuild_from_store
from vision.matcher import cosine_similarity, is_embedding, l2_normalize

IDENTITIES_DIR = DATA_DIR / "identities"


@dataclass
class IdentityRecord:
    id: str
    name: str
    enrolled_at: str
    embeddings: List[list] = field(default_factory=list)
    master_embedding: Optional[list] = None
    image_paths: List[str] = field(default_factory=list)
    poses: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_face_db_entry(self) -> List[list]:
        if self.embeddings:
            return [l2_normalize(e) for e in self.embeddings if is_embedding(e)]
        if self.master_embedding:
            return [l2_normalize(self.master_embedding)]
        return []


class IdentityStore:
    def __init__(self, settings: dict):
        self.settings = settings
        self.max_embeddings = int(settings.get("max_embeddings_per_person", 25))
        self._records: Dict[str, IdentityRecord] = {}
        ensure_directories()
        IDENTITIES_DIR.mkdir(parents=True, exist_ok=True)

    def reset(self, *, clear_captures: bool = True):
        if IDENTITIES_DIR.exists():
            shutil.rmtree(IDENTITIES_DIR, ignore_errors=True)
        IDENTITIES_DIR.mkdir(parents=True, exist_ok=True)
        self._records.clear()

    def _calibrate_record(self, rec: IdentityRecord) -> None:
        if not rec.embeddings or rec.master_embedding is None:
            return
        master = np.asarray(rec.master_embedding, dtype=np.float32)
        scores = [
            cosine_similarity(master, s) for s in rec.embeddings if is_embedding(s)
        ]
        if not scores:
            return
        meta = dict(rec.metadata or {})
        min_auto = int(self.settings.get("enrollment_min_auto_save", 8))
        sparse = len(rec.embeddings) < min_auto
        meta["calibration"] = {
            "enroll_score_mean": float(np.mean(scores)),
            "enroll_score_min": float(np.min(scores)),
            "sparse_enroll": sparse,
            "enroll_sample_count": len(rec.embeddings),
        }
        rec.metadata = meta

    def load(self):
        self._records.clear()
        if not IDENTITIES_DIR.exists():
            rebuild_from_store([])
            return self.build_face_db()
        for entry in IDENTITIES_DIR.iterdir():
            if not entry.is_dir():
                continue
            meta_path = entry / "meta.json"
            emb_path = entry / "embeddings.npy"
            if not meta_path.exists():
                continue
            with open(meta_path) as f:
                data = json.load(f)
            rec = IdentityRecord(**{k: data[k] for k in IdentityRecord.__dataclass_fields__ if k in data})
            if emb_path.exists():
                arr = np.load(emb_path)
                if arr.ndim == 2:
                    rec.embeddings = [l2_normalize(row) for row in arr]
                elif arr.ndim == 1:
                    rec.embeddings = [l2_normalize(arr)]
            self._records[rec.id] = rec
        rebuild_from_store(self._records.values())
        return self.build_face_db()

    def build_face_db(self) -> Dict[str, List]:
        """Name-keyed dict for matcher compatibility."""
        db: Dict[str, List] = {}
        for rec in self._records.values():
            samples = rec.to_face_db_entry()
            if samples:
                db[rec.name] = samples[: self.max_embeddings]
        return db

    def save_record(self, rec: IdentityRecord):
        folder = IDENTITIES_DIR / rec.id
        folder.mkdir(parents=True, exist_ok=True)
        meta = asdict(rec)
        meta.pop("embeddings", None)
        with open(folder / "meta.json", "w") as f:
            json.dump(meta, f, indent=2)
        if rec.embeddings:
            np.save(
                folder / "embeddings.npy",
                np.array(rec.embeddings, dtype=np.float32),
            )
        self._records[rec.id] = rec

    def add_person(
        self,
        name: str,
        embeddings: List,
        *,
        image_path: Optional[str] = None,
        poses: Optional[List[str]] = None,
        profile: Optional[dict] = None,
    ) -> IdentityRecord:
        normed = [l2_normalize(e) for e in embeddings if is_embedding(e)]
        master = l2_normalize(np.mean(np.array(normed), axis=0)) if normed else None
        rec_id = str(uuid.uuid4())
        folder = IDENTITIES_DIR / rec_id
        folder.mkdir(parents=True, exist_ok=True)
        images_dir = folder / "images"
        images_dir.mkdir(exist_ok=True)

        image_paths = []
        if image_path and os.path.isfile(image_path):
            dest = images_dir / os.path.basename(image_path)
            shutil.copy2(image_path, dest)
            image_paths.append(str(dest))

        meta = dict(profile or {})
        rec = IdentityRecord(
            id=rec_id,
            name=name,
            enrolled_at=datetime.now(timezone.utc).isoformat(),
            embeddings=normed[: self.max_embeddings],
            master_embedding=master,
            image_paths=image_paths,
            poses=poses or [],
            metadata=meta,
        )
        self._calibrate_record(rec)
        self.save_record(rec)
        rebuild_from_store(self._records.values())
        return rec

    def delete(self, rec_id: str) -> bool:
        rec = self._records.pop(rec_id, None)
        if rec is None:
            return False
        folder = IDENTITIES_DIR / rec_id
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        return True

    def find_by_name(self, name: str) -> Optional[IdentityRecord]:
        key = name.strip().lower()
        for rec in self._records.values():
            if rec.name.strip().lower() == key:
                return rec
        return None

    def rename_person(self, old_name: str, new_name: str) -> Optional[IdentityRecord]:
        rec = self.find_by_name(old_name)
        if rec is None:
            return None
        new_name = new_name.strip()
        if not new_name:
            return None
        existing = self.find_by_name(new_name)
        if existing is not None and existing.id != rec.id:
            return None
        rec.name = new_name
        meta = dict(rec.metadata or {})
        meta["name"] = new_name
        rec.metadata = meta
        self.save_record(rec)
        rebuild_from_store(self._records.values())
        return rec

    def list_profiles(self) -> List[dict]:
        out = []
        for rec in self._records.values():
            thumb = rec.image_paths[0] if rec.image_paths else None
            meta = rec.metadata or {}
            out.append(
                {
                    "id": rec.id,
                    "name": rec.name,
                    "age": meta.get("age", ""),
                    "status": meta.get("status", ""),
                    "image": thumb,
                    "enrolled_at": rec.enrolled_at,
                }
            )
        return out

    def add_embedding(self, name: str, embedding) -> bool:
        rec = self.find_by_name(name)
        if rec is None:
            rec = self.add_person(name, [embedding])
            return True
        emb = l2_normalize(embedding)
        rec.embeddings.append(emb)
        if len(rec.embeddings) > self.max_embeddings:
            rec.embeddings = rec.embeddings[-self.max_embeddings :]
        rec.master_embedding = l2_normalize(
            np.mean(np.array(rec.embeddings), axis=0)
        )
        self._calibrate_record(rec)
        self.save_record(rec)
        rebuild_from_store(self._records.values())
        return True

    def embedding_is_new(self, name: str, embedding) -> bool:
        rec = self.find_by_name(name)
        if not rec or not rec.embeddings:
            return True
        best = max(cosine_similarity(embedding, s) for s in rec.embeddings)
        min_dist = float(self.settings.get("min_new_embedding_distance", 0.02))
        return (1.0 - best) >= min_dist
