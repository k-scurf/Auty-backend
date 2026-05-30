"""Tenant-scoped face embedding persistence (replaces face_db.pkl per tenant)."""

from __future__ import annotations

import io
import time
import uuid
from typing import Dict, List, Optional

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from auty.db.models import Embedding, Employee

_GALLERY_CACHE: Dict[uuid.UUID, tuple[float, Dict[str, List[np.ndarray]]]] = {}
_CACHE_TTL_SEC = 30.0


def serialize_embedding(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, np.asarray(arr, dtype=np.float32), allow_pickle=False)
    return buf.getvalue()


def deserialize_embedding(data: bytes) -> np.ndarray:
    buf = io.BytesIO(data)
    return np.load(buf, allow_pickle=False)


def invalidate_tenant_gallery(tenant_id: uuid.UUID) -> None:
    _GALLERY_CACHE.pop(tenant_id, None)


def save_embeddings(
    db: Session,
    employee_id: uuid.UUID,
    tenant_id: uuid.UUID,
    embeddings: List[np.ndarray],
) -> None:
    """Replace all embeddings for one employee within a tenant."""
    db.execute(
        delete(Embedding).where(
            Embedding.tenant_id == tenant_id,
            Embedding.employee_id == employee_id,
        )
    )
    for arr in embeddings:
        if arr is None or np.asarray(arr).size == 0:
            continue
        db.add(
            Embedding(
                tenant_id=tenant_id,
                employee_id=employee_id,
                embedding=serialize_embedding(np.asarray(arr, dtype=np.float32)),
            )
        )
    db.commit()
    invalidate_tenant_gallery(tenant_id)


def delete_tenant_embeddings(db: Session, tenant_id: uuid.UUID) -> int:
    """Delete embedding rows for a tenant (employees may remain)."""
    result = db.execute(delete(Embedding).where(Embedding.tenant_id == tenant_id))
    db.commit()
    invalidate_tenant_gallery(tenant_id)
    return int(result.rowcount or 0)


def load_tenant_gallery(db: Session, tenant_id: uuid.UUID) -> Dict[str, List[np.ndarray]]:
    """All embeddings for a tenant, grouped by employee display name."""
    now = time.time()
    cached = _GALLERY_CACHE.get(tenant_id)
    if cached is not None and (now - cached[0]) < _CACHE_TTL_SEC:
        return cached[1]

    stmt = (
        select(Employee.name, Embedding.embedding)
        .join(Embedding, Embedding.employee_id == Employee.id)
        .where(
            Employee.tenant_id == tenant_id,
            Embedding.tenant_id == tenant_id,
        )
    )
    gallery: Dict[str, List[np.ndarray]] = {}
    for name, blob in db.execute(stmt):
        if not blob:
            continue
        gallery.setdefault(name, []).append(deserialize_embedding(blob))

    _GALLERY_CACHE[tenant_id] = (now, gallery)
    return gallery


def gallery_from_identity_store(store, tenant_employee_ids: Optional[set[str]] = None) -> Dict[str, List[np.ndarray]]:
    """Build a name → embeddings dict from in-memory IdentityStore (legacy fallback)."""
    gallery: Dict[str, List[np.ndarray]] = {}
    for rec in store._records.values():
        if tenant_employee_ids is not None and rec.id not in tenant_employee_ids:
            continue
        samples = rec.to_face_db_entry()
        if samples:
            gallery[rec.name] = [np.asarray(s, dtype=np.float32) for s in samples]
    return gallery
