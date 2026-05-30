#!/usr/bin/env python3
"""
One-time migration of file-based Auty data into PostgreSQL for the default tenant.

Idempotent: safe to run multiple times — skips rows that already exist.

Usage:
  export DATABASE_URL=postgresql://user:pass@host:5432/dbname
  python scripts/migrate_to_postgres.py
"""

from __future__ import annotations

import json
import os
import pickle
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from auty.db.bootstrap import get_or_create_default_tenant
from auty.db.connection import get_database_url, get_session_factory
from auty.db.embedding_store import invalidate_tenant_gallery, save_embeddings
from auty.db.init_db import create_all_tables
from auty.db.models import Attendance, Consent, Employee, Embedding, Setting
from auty.db.repositories import upsert_settings
from utils.paths import (
    ATTENDANCE_LOG_PATH,
    CONSENT_LOG_PATH,
    DATA_DIR,
    FACE_DB_PATH,
    PROFILES_PATH,
    SCHEDULES_PATH,
    ensure_directories,
)

IDENTITIES_DIR = DATA_DIR / "identities"
CONSENT_ALT_PATH = DATA_DIR / "consent_records.json"

# Skip internal settings keys that should not be tenant rows
_SETTINGS_SKIP = frozenset({"memory_file", "log_file"})


def _parse_enrolled_at(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _load_identity_meta() -> Dict[str, dict]:
    """Map display name (lower) and id → meta record."""
    by_name: Dict[str, dict] = {}
    by_id: Dict[str, dict] = {}
    if not IDENTITIES_DIR.is_dir():
        return by_name
    for folder in IDENTITIES_DIR.iterdir():
        if not folder.is_dir():
            continue
        meta_path = folder / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        name = str(meta.get("name") or "").strip()
        rec_id = str(meta.get("id") or folder.name)
        meta["_folder_id"] = folder.name
        if name:
            by_name[name.lower()] = meta
        by_id[rec_id] = meta
    return by_name


def _stable_employee_id(tenant_id: uuid.UUID, name: str) -> uuid.UUID:
    return uuid.uuid5(tenant_id, name.strip().lower())


def _resolve_employee_id(
    tenant_id: uuid.UUID,
    profile_key: str,
    prof: dict,
    identity_by_name: Dict[str, dict],
) -> uuid.UUID:
    for candidate in (
        prof.get("id"),
        identity_by_name.get(profile_key.lower(), {}).get("id"),
        identity_by_name.get(str(prof.get("name", "")).lower(), {}).get("id"),
    ):
        if candidate:
            try:
                return uuid.UUID(str(candidate))
            except ValueError:
                pass
    display = str(prof.get("name") or profile_key).strip()
    return _stable_employee_id(tenant_id, display)


def _load_face_db() -> Dict[str, List[np.ndarray]]:
    """Name → list of embedding arrays from pickle and/or identity npy files."""
    import recognition as rec

    gallery: Dict[str, List[np.ndarray]] = {}

    if FACE_DB_PATH.is_file():
        try:
            with open(FACE_DB_PATH, "rb") as f:
                raw = pickle.load(f)
        except (OSError, pickle.UnpicklingError, EOFError, ValueError) as exc:
            print(f"[migrate] face_db.pkl skipped: {exc}")
            raw = {}
        if isinstance(raw, dict):
            for name, value in raw.items():
                samples: List[np.ndarray] = []
                if rec.is_embedding(value):
                    samples = [np.asarray(rec.l2_normalize(value), dtype=np.float32)]
                elif isinstance(value, (list, tuple)):
                    samples = [
                        np.asarray(rec.l2_normalize(s), dtype=np.float32)
                        for s in value
                        if rec.is_embedding(s)
                    ]
                if samples:
                    gallery[str(name)] = samples

    if IDENTITIES_DIR.is_dir():
        for folder in IDENTITIES_DIR.iterdir():
            if not folder.is_dir():
                continue
            npy_path = folder / "embeddings.npy"
            meta_path = folder / "meta.json"
            if not npy_path.is_file():
                continue
            name = folder.name
            if meta_path.is_file():
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    name = str(meta.get("name") or name)
                except (OSError, json.JSONDecodeError):
                    pass
            try:
                arr = np.load(npy_path, allow_pickle=False)
                if arr.ndim == 1:
                    gallery[name] = [np.asarray(arr, dtype=np.float32)]
                else:
                    gallery[name] = [
                        np.asarray(row, dtype=np.float32) for row in arr
                    ]
            except (OSError, ValueError):
                continue

    return gallery


def migrate_employees(db, tenant_id: uuid.UUID) -> tuple[int, Dict[str, uuid.UUID]]:
    """Returns (inserted_count, name_lower → employee_id)."""
    if not PROFILES_PATH.is_file():
        print("[migrate] No profiles.json — skipping employees")
        return 0, {}

    with open(PROFILES_PATH, "r", encoding="utf-8") as f:
        profiles = json.load(f)
    if not isinstance(profiles, dict):
        profiles = {}

    identity_by_name = _load_identity_meta()
    name_to_id: Dict[str, uuid.UUID] = {}
    inserted = 0

    existing_rows = db.scalars(
        select(Employee).where(Employee.tenant_id == tenant_id)
    ).all()
    for row in existing_rows:
        name_to_id[row.name.lower()] = row.id

    for key, prof in profiles.items():
        if not isinstance(prof, dict):
            prof = {"name": str(key)}
        display = str(prof.get("name") or key).strip()
        if not display:
            continue

        eid = _resolve_employee_id(tenant_id, key, prof, identity_by_name)
        if display.lower() in name_to_id:
            continue

        existing = db.scalar(
            select(Employee).where(
                Employee.tenant_id == tenant_id,
                Employee.id == eid,
            )
        )
        if existing is not None:
            name_to_id[display.lower()] = existing.id
            continue

        row = Employee(
            id=eid,
            tenant_id=tenant_id,
            name=display,
            age=str(prof.get("age") or ""),
            status=str(prof.get("status") or ""),
            photo_path=prof.get("image"),
            enrolled_at=_parse_enrolled_at(
                prof.get("enrolled_at")
                or identity_by_name.get(display.lower(), {}).get("enrolled_at")
            ),
        )
        db.add(row)
        name_to_id[display.lower()] = eid
        inserted += 1

    db.commit()
    return inserted, name_to_id


def migrate_embeddings(
    db,
    tenant_id: uuid.UUID,
    name_to_id: Dict[str, uuid.UUID],
) -> int:
    gallery = _load_face_db()
    inserted_employees = 0
    inserted_vectors = 0

    for name, arrays in gallery.items():
        eid = name_to_id.get(name.lower())
        if eid is None:
            eid = db.scalar(
                select(Employee.id).where(
                    Employee.tenant_id == tenant_id,
                    Employee.name == name,
                )
            )
        if eid is None:
            eid = _stable_employee_id(tenant_id, name)
            if db.scalar(select(Employee.id).where(Employee.id == eid)) is None:
                db.add(
                    Employee(
                        id=eid,
                        tenant_id=tenant_id,
                        name=name,
                        enrolled_at=datetime.now(timezone.utc),
                    )
                )
                db.commit()
                name_to_id[name.lower()] = eid
                inserted_employees += 1

        count = db.scalar(
            select(func.count())
            .select_from(Embedding)
            .where(
                Embedding.tenant_id == tenant_id,
                Embedding.employee_id == eid,
            )
        )
        if count and int(count) > 0:
            continue

        save_embeddings(db, eid, tenant_id, arrays)
        inserted_vectors += len(arrays)

    return inserted_vectors


def migrate_attendance(db, tenant_id: uuid.UUID, name_to_id: Dict[str, uuid.UUID]) -> int:
    if not ATTENDANCE_LOG_PATH.is_file():
        print("[migrate] No attendance_log.jsonl — skipping attendance")
        return 0

    existing_ids = {
        row
        for row in db.scalars(
            select(Attendance.id).where(Attendance.tenant_id == tenant_id)
        ).all()
    }

    inserted = 0
    with open(ATTENDANCE_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            raw_id = ev.get("id")
            if not raw_id:
                continue
            try:
                event_id = uuid.UUID(str(raw_id))
            except ValueError:
                continue
            if event_id in existing_ids:
                continue

            emp_name = str(ev.get("name") or "")
            emp_id_raw = ev.get("employee_id") or emp_name
            employee_uuid: Optional[uuid.UUID] = None
            try:
                employee_uuid = uuid.UUID(str(emp_id_raw))
            except ValueError:
                employee_uuid = name_to_id.get(emp_name.lower())

            meta = {
                "confidence": ev.get("confidence", 0.0),
                "device_id": ev.get("device_id", ""),
                "snapshot_path": ev.get("snapshot_path"),
            }
            ts = float(ev.get("timestamp_ts") or 0.0)
            created = _parse_enrolled_at(ev.get("timestamp_utc")) or datetime.fromtimestamp(
                ts, tz=timezone.utc
            )

            db.add(
                Attendance(
                    id=event_id,
                    tenant_id=tenant_id,
                    employee_id=employee_uuid,
                    employee_name=emp_name,
                    event=str(ev.get("event") or ""),
                    timestamp_ts=ts,
                    location_id=str(ev.get("location_id") or ""),
                    note=json.dumps({"_meta": meta, "notes": []}),
                    created_at=created,
                )
            )
            existing_ids.add(event_id)
            inserted += 1

    db.commit()
    return inserted


def migrate_settings(db, tenant_id: uuid.UUID) -> int:
    settings_path = Path(
        os.environ.get("AUTY_CONFIG", str(DATA_DIR / "settings.json"))
    ).resolve()
    if not settings_path.is_file():
        print("[migrate] No settings.json — skipping settings")
        return 0

    with open(settings_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return 0

    existing_keys = set(
        db.scalars(
            select(Setting.key).where(Setting.tenant_id == tenant_id)
        ).all()
    )

    updates = {
        k: v
        for k, v in data.items()
        if k not in _SETTINGS_SKIP and k not in existing_keys
    }
    if not updates:
        return 0
    upsert_settings(db, tenant_id, updates)
    return len(updates)


def _load_consent_file() -> Dict[str, dict]:
    for path in (CONSENT_LOG_PATH, CONSENT_ALT_PATH):
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
            except (OSError, json.JSONDecodeError):
                pass
    return {}


def migrate_consent(db, tenant_id: uuid.UUID) -> int:
    records = _load_consent_file()
    if not records:
        print("[migrate] No consent_log.json — skipping consent")
        return 0

    existing = {
        (row.employee_id, row.timestamp_utc)
        for row in db.scalars(
            select(Consent.employee_id, Consent.timestamp_utc).where(
                Consent.tenant_id == tenant_id
            )
        ).all()
    }

    inserted = 0
    for employee_id, record in records.items():
        if not isinstance(record, dict):
            continue
        ts = _parse_enrolled_at(record.get("timestamp_utc")) or datetime.now(
            timezone.utc
        )
        key = (str(employee_id), ts)
        if key in existing:
            continue

        db.add(
            Consent(
                tenant_id=tenant_id,
                employee_id=str(employee_id),
                employee_name=str(record.get("name") or ""),
                consented=bool(record.get("consent_given", False)),
                ip_address=str(record.get("ip_address") or ""),
                form_version=str(record.get("form_version") or ""),
                timestamp_utc=ts,
            )
        )
        existing.add(key)
        inserted += 1

    db.commit()
    return inserted


def migrate_schedules(db, tenant_id: uuid.UUID) -> int:
    """Optional: migrate schedules.json if present."""
    if not SCHEDULES_PATH.is_file():
        return 0

    from auty.db.models import Schedule
    from auty.db.repositories import save_schedule

    try:
        with open(SCHEDULES_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0

    schedules = raw.get("schedules", raw if isinstance(raw, dict) else {})
    if not isinstance(schedules, dict):
        return 0

    inserted = 0
    for employee_id, sched in schedules.items():
        if not isinstance(sched, dict):
            continue
        exists = db.scalar(
            select(Schedule.id).where(
                Schedule.tenant_id == tenant_id,
                Schedule.employee_id == str(employee_id),
            )
        )
        if exists:
            continue
        save_schedule(db, tenant_id, str(employee_id), sched)
        inserted += 1
    return inserted


def main() -> int:
    if not get_database_url():
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        return 1

    ensure_directories()
    create_all_tables()

    db = get_session_factory()()
    try:
        tenant = get_or_create_default_tenant(db)
        tenant_id = tenant.id
        print(f"[migrate] Using tenant {tenant.username!r} id={tenant_id}")

        emp_count, name_to_id = migrate_employees(db, tenant_id)
        emb_count = migrate_embeddings(db, tenant_id, name_to_id)
        att_count = migrate_attendance(db, tenant_id, name_to_id)
        set_count = migrate_settings(db, tenant_id)
        con_count = migrate_consent(db, tenant_id)
        sch_count = migrate_schedules(db, tenant_id)

        invalidate_tenant_gallery(tenant_id)

        print(
            f"[migrate] Done — employees: {emp_count} new, "
            f"embeddings: {emb_count} vectors, "
            f"attendance: {att_count} events, "
            f"settings: {set_count} keys, "
            f"consent: {con_count} records"
            + (f", schedules: {sch_count}" if sch_count else "")
        )
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
