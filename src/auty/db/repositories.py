"""Tenant-scoped PostgreSQL data access."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from auty.db.models import (
    Attendance,
    AuditLog,
    Consent,
    Employee,
    Schedule,
    Setting,
)
from utils.paths import DATA_DIR

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def tenant_photos_dir(tenant_id: uuid.UUID) -> Path:
    path = DATA_DIR / str(tenant_id) / "photos"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Employees (profiles)
# ---------------------------------------------------------------------------


def list_employees(db: Session, tenant_id: uuid.UUID) -> list[dict]:
    rows = db.scalars(
        select(Employee)
        .where(Employee.tenant_id == tenant_id)
        .order_by(Employee.name)
    ).all()
    out = []
    for row in rows:
        out.append(_employee_to_profile(row))
    return out


def _employee_to_profile(row: Employee) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "age": row.age or "",
        "status": row.status or "",
        "image": row.photo_path,
        "enrolled_at": row.enrolled_at.isoformat() if row.enrolled_at else None,
    }


def get_employee_by_id(
    db: Session, tenant_id: uuid.UUID, employee_id: uuid.UUID
) -> Optional[Employee]:
    return db.scalar(
        select(Employee).where(
            Employee.tenant_id == tenant_id,
            Employee.id == employee_id,
        )
    )


def get_employee_by_name(
    db: Session, tenant_id: uuid.UUID, name: str
) -> Optional[Employee]:
    return db.scalar(
        select(Employee).where(
            Employee.tenant_id == tenant_id,
            Employee.name == name,
        )
    )


def create_employee(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    name: str,
    age: str = "",
    status: str = "FRIEND",
    photo_path: Optional[str] = None,
    employee_id: Optional[uuid.UUID] = None,
) -> Employee:
    row = Employee(
        id=employee_id or uuid.uuid4(),
        tenant_id=tenant_id,
        name=name.strip(),
        age=age or "",
        status=status or "FRIEND",
        photo_path=photo_path,
        enrolled_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_employee(
    db: Session,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    **fields: Any,
) -> Optional[Employee]:
    row = get_employee_by_id(db, tenant_id, employee_id)
    if row is None:
        return None
    for key, value in fields.items():
        if hasattr(row, key):
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def delete_employee(db: Session, tenant_id: uuid.UUID, employee_id: uuid.UUID) -> bool:
    row = get_employee_by_id(db, tenant_id, employee_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def delete_employee_by_name(db: Session, tenant_id: uuid.UUID, name: str) -> bool:
    row = get_employee_by_name(db, tenant_id, name)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def reset_tenant_data(db: Session, tenant_id: uuid.UUID) -> None:
    """Remove tenant-scoped rows (embeddings cascade via employees)."""
    db.execute(delete(Attendance).where(Attendance.tenant_id == tenant_id))
    db.execute(delete(Schedule).where(Schedule.tenant_id == tenant_id))
    db.execute(delete(Consent).where(Consent.tenant_id == tenant_id))
    db.execute(delete(Setting).where(Setting.tenant_id == tenant_id))
    db.execute(delete(Employee).where(Employee.tenant_id == tenant_id))
    db.commit()
    photos = tenant_photos_dir(tenant_id)
    for path in photos.glob("*"):
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def get_settings_dict(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    rows = db.scalars(select(Setting).where(Setting.tenant_id == tenant_id)).all()
    return {row.key: row.value for row in rows}


def upsert_settings(db: Session, tenant_id: uuid.UUID, updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        row = db.scalar(
            select(Setting).where(
                Setting.tenant_id == tenant_id,
                Setting.key == key,
            )
        )
        if row is None:
            db.add(Setting(tenant_id=tenant_id, key=key, value=value))
        else:
            row.value = value
    db.commit()


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


def get_schedule(
    db: Session, tenant_id: uuid.UUID, employee_id: str
) -> Optional[dict]:
    row = db.scalar(
        select(Schedule).where(
            Schedule.tenant_id == tenant_id,
            Schedule.employee_id == str(employee_id),
        )
    )
    if row is None:
        return None
    return {
        "employee_id": row.employee_id,
        "name": "",
        "timezone": row.timezone,
        "days": row.days or {},
    }


def save_schedule(
    db: Session, tenant_id: uuid.UUID, employee_id: str, data: dict
) -> dict:
    row = db.scalar(
        select(Schedule).where(
            Schedule.tenant_id == tenant_id,
            Schedule.employee_id == str(employee_id),
        )
    )
    days = data.get("days") or {}
    timezone_name = str(data.get("timezone") or "America/Chicago")
    if row is None:
        row = Schedule(
            tenant_id=tenant_id,
            employee_id=str(employee_id),
            days=days,
            timezone=timezone_name,
        )
        db.add(row)
    else:
        row.days = days
        row.timezone = timezone_name
    db.commit()
    db.refresh(row)
    return {
        "employee_id": row.employee_id,
        "name": str(data.get("name") or ""),
        "timezone": row.timezone,
        "days": row.days or {},
    }


def all_schedules(db: Session, tenant_id: uuid.UUID) -> dict[str, dict]:
    rows = db.scalars(select(Schedule).where(Schedule.tenant_id == tenant_id)).all()
    return {
        row.employee_id: {
            "employee_id": row.employee_id,
            "name": "",
            "timezone": row.timezone,
            "days": row.days or {},
        }
        for row in rows
    }


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------


def record_consent(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    employee_id: str,
    employee_name: str,
    ip_address: str,
    form_version: str,
) -> None:
    db.add(
        Consent(
            tenant_id=tenant_id,
            employee_id=str(employee_id),
            employee_name=employee_name,
            consented=True,
            ip_address=ip_address,
            form_version=form_version,
            timestamp_utc=datetime.now(timezone.utc),
        )
    )
    db.commit()


def get_consent(
    db: Session, tenant_id: uuid.UUID, employee_id: str
) -> Optional[dict]:
    rows = db.scalars(
        select(Consent)
        .where(
            Consent.tenant_id == tenant_id,
            Consent.employee_id == str(employee_id),
        )
        .order_by(Consent.timestamp_utc.desc())
    ).all()
    if not rows:
        return None
    row = rows[0]
    return {
        "employee_id": row.employee_id,
        "consent_given": row.consented,
        "timestamp_utc": row.timestamp_utc.isoformat().replace("+00:00", "Z"),
        "form_version": row.form_version,
    }


def request_consent_deletion(
    db: Session, tenant_id: uuid.UUID, employee_id: str
) -> None:
    db.add(
        Consent(
            tenant_id=tenant_id,
            employee_id=str(employee_id),
            employee_name="",
            consented=False,
            ip_address="",
            form_version="deletion_requested",
            timestamp_utc=datetime.now(timezone.utc),
        )
    )
    db.commit()


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------


def _parse_note_payload(note_field: Optional[str]) -> tuple[dict, list[dict]]:
    if not note_field:
        return {}, []
    try:
        parsed = json.loads(note_field)
        if isinstance(parsed, dict):
            meta = parsed.get("_meta") if isinstance(parsed.get("_meta"), dict) else {}
            notes = parsed.get("notes") if isinstance(parsed.get("notes"), list) else []
            if meta or notes:
                return meta, notes
        if isinstance(parsed, list):
            return {}, parsed
    except json.JSONDecodeError:
        pass
    return {}, []


def _attendance_row_to_dict(row: Attendance) -> dict:
    meta, notes = _parse_note_payload(row.note)
    emp_id = str(row.employee_id) if row.employee_id else (row.employee_name or "")
    return {
        "id": str(row.id),
        "employee_id": emp_id,
        "name": row.employee_name or "",
        "event": row.event,
        "timestamp_utc": row.created_at.isoformat().replace("+00:00", "Z"),
        "timestamp_ts": float(row.timestamp_ts),
        "location_id": row.location_id or "",
        "confidence": float(meta.get("confidence", 0.0)),
        "device_id": str(meta.get("device_id", "")),
        "snapshot_path": meta.get("snapshot_path"),
        "notes": notes,
    }


def insert_attendance_event(
    db: Session,
    tenant_id: uuid.UUID,
    event: dict,
) -> None:
    """Persist a clock event dict (from AttendanceTracker)."""
    emp_id_raw = event.get("employee_id") or event.get("name")
    employee_uuid: Optional[uuid.UUID] = None
    try:
        employee_uuid = uuid.UUID(str(emp_id_raw))
    except (ValueError, TypeError):
        employee_uuid = None

    meta = {
        "confidence": event.get("confidence", 0.0),
        "device_id": event.get("device_id", ""),
        "snapshot_path": event.get("snapshot_path"),
    }
    row = Attendance(
        id=uuid.UUID(str(event["id"])) if event.get("id") else uuid.uuid4(),
        tenant_id=tenant_id,
        employee_id=employee_uuid,
        employee_name=str(event.get("name") or ""),
        event=str(event.get("event") or ""),
        timestamp_ts=float(event.get("timestamp_ts") or 0.0),
        location_id=str(event.get("location_id") or ""),
        note=json.dumps({"_meta": meta, "notes": []}),
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()


def list_attendance_events(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    start_ts: Optional[float] = None,
    end_ts: Optional[float] = None,
    employee_name: Optional[str] = None,
    location_id: Optional[str] = None,
) -> list[dict]:
    q = select(Attendance).where(Attendance.tenant_id == tenant_id)
    rows = db.scalars(q.order_by(Attendance.timestamp_ts)).all()
    out: list[dict] = []
    for row in rows:
        if start_ts is not None and row.timestamp_ts < start_ts:
            continue
        if end_ts is not None and row.timestamp_ts > end_ts:
            continue
        ev = _attendance_row_to_dict(row)
        if employee_name and ev.get("name") != employee_name:
            continue
        if location_id and ev.get("location_id") != location_id:
            continue
        out.append(ev)
    return out


def add_attendance_note(
    db: Session,
    tenant_id: uuid.UUID,
    event_id: str,
    note: str,
    manager: str,
) -> bool:
    try:
        eid = uuid.UUID(event_id)
    except ValueError:
        return False
    row = db.scalar(
        select(Attendance).where(
            Attendance.tenant_id == tenant_id,
            Attendance.id == eid,
        )
    )
    if row is None:
        return False
    meta, notes = _parse_note_payload(row.note)
    notes.append(
        {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "manager": manager,
            "note": note,
        }
    )
    row.note = json.dumps({"_meta": meta, "notes": notes})
    db.commit()
    return True


def attendance_active_snapshot(db: Session, tenant_id: uuid.UUID) -> dict:
    """Derive clocked-in list from attendance rows."""
    events = list_attendance_events(db, tenant_id)
    by_name: dict[str, list[dict]] = {}
    for ev in events:
        name = ev.get("name") or ""
        if not name:
            continue
        by_name.setdefault(name, []).append(ev)

    clocked_in = []
    recent = sorted(events, key=lambda e: e.get("timestamp_ts", 0))[-10:]
    for name, evs in by_name.items():
        last = evs[-1]
        if last.get("event") == "CLOCK_IN":
            clocked_in.append(
                {
                    "employee_id": last.get("employee_id", name),
                    "name": name,
                    "clock_in_ts": last.get("timestamp_ts"),
                    "clock_in_utc": last.get("timestamp_utc"),
                    "duration_seconds": max(
                        0,
                        int(
                            datetime.now(timezone.utc).timestamp()
                            - float(last.get("timestamp_ts") or 0)
                        ),
                    ),
                    "location_id": last.get("location_id", ""),
                }
            )
    return {
        "clocked_in": sorted(clocked_in, key=lambda e: e["clock_in_ts"]),
        "recent_events": recent,
        "alerts": [],
    }


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def append_audit(
    db: Session,
    tenant_id: uuid.UUID,
    action: str,
    *,
    actor: str = "system",
    detail: str = "",
) -> None:
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            action=action,
            actor=actor,
            detail=detail,
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()


def list_audit(db: Session, tenant_id: uuid.UUID, limit: int = 50) -> list[dict]:
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.tenant_id == tenant_id)
        .order_by(AuditLog.created_at.desc())
        .limit(max(1, min(limit, 500)))
    ).all()
    return [
        {
            "timestamp_utc": row.created_at.isoformat().replace("+00:00", "Z"),
            "action": row.action,
            "actor": row.actor or "",
            "detail": row.detail or "",
        }
        for row in rows
    ]
