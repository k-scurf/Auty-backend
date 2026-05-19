"""
Offline multi-pose database builder.

Place JPGs in scripts/profile_sources/ (e.g. alice_front.jpg).
Run from repo root: python3 scripts/build_db.py
"""

import json
import os
import pickle
import sys

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import recognition as rec
from utils.paths import FACE_DB_PATH, default_settings_path, ensure_directories

PROFILE_FOLDER = os.path.join(os.path.dirname(__file__), "profile_sources")
DB_FILE = str(FACE_DB_PATH)


def load_settings():
    path = default_settings_path()
    if path.exists():
        with open(path) as f:
            return json.load(f)
    example = os.path.join(ROOT, "config", "settings.example.json")
    if os.path.exists(example):
        with open(example) as f:
            return json.load(f)
    return {}


def main():
    ensure_directories()
    os.makedirs(PROFILE_FOLDER, exist_ok=True)
    rec.configure({**load_settings(), "model_name": "ArcFace", "use_face_alignment": True})

    db = {}
    for file in sorted(os.listdir(PROFILE_FOLDER)):
        if not file.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        name = os.path.splitext(file)[0]
        path = os.path.join(PROFILE_FOLDER, file)
        bgr = cv2.imread(path)
        if bgr is None:
            print("Skip (unreadable):", file)
            continue
        h, w = bgr.shape[:2]
        aligned = rec.align_face(bgr, 0, 0, w, h)
        embedding = rec.extract_embedding(
            aligned, already_aligned=rec.is_aligned_crop(aligned)
        )
        if embedding is None:
            print("Skip (no embedding):", file)
            continue
        db.setdefault(name, []).append(embedding)
        print(f"Encoded: {name}  (samples: {len(db[name])})")

    with open(DB_FILE, "wb") as f:
        pickle.dump(db, f)
    print(
        f"Done — {len(db)} people, "
        f"{sum(len(v) for v in db.values())} embeddings -> {DB_FILE}"
    )


if __name__ == "__main__":
    main()
