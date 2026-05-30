"""Bootstrap default tenant on first startup."""

from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from auty.auth import hash_password
from auty.db.models import Tenant


def get_or_create_default_tenant(db: Session) -> Tenant:
    """Return the default owner tenant, creating it if missing."""
    username = str(os.environ.get("AUTY_MANAGER_USERNAME") or "owner").strip()
    tenant = db.scalar(select(Tenant).where(Tenant.username == username))
    if tenant is not None:
        return tenant

    if db.scalar(select(Tenant.id).limit(1)) is None:
        ensure_default_tenant(db)
        tenant = db.scalar(select(Tenant).where(Tenant.username == username))
        if tenant is not None:
            return tenant

    password = str(os.environ.get("AUTY_MANAGER_PASSWORD") or "1234")
    name = str(os.environ.get("AUTY_DEFAULT_TENANT_NAME") or "Default").strip()
    tenant = Tenant(
        name=name,
        username=username,
        password_hash=hash_password(password),
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    print(f"[Auty] Created default tenant id={tenant.id} username={username!r}")
    return tenant


def ensure_default_tenant(db: Session) -> None:
    """Create a default tenant if the tenants table is empty."""
    existing = db.scalar(select(Tenant.id).limit(1))
    if existing is not None:
        return

    username = str(os.environ.get("AUTY_MANAGER_USERNAME") or "owner").strip()
    password = str(os.environ.get("AUTY_MANAGER_PASSWORD") or "1234")
    name = str(os.environ.get("AUTY_DEFAULT_TENANT_NAME") or "Default").strip()

    tenant = Tenant(
        name=name,
        username=username,
        password_hash=hash_password(password),
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    print(
        f"[Auty] Created default tenant id={tenant.id} username={username!r} "
        f"(password from AUTY_MANAGER_PASSWORD env or default '1234')"
    )
