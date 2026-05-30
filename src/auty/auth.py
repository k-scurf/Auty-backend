"""JWT authentication and tenant-scoped FastAPI dependencies."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from auty.db.connection import get_database_url, get_session_factory
from auty.db.context import set_current_tenant
from auty.db.models import Tenant

_default_tenant_id: Optional[uuid.UUID] = None

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 12

_bearer = HTTPBearer(auto_error=False)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def _jwt_secret() -> str:
    secret = (
        os.environ.get("JWT_SECRET", "").strip()
        or os.environ.get("AUTY_JWT_SECRET", "").strip()
        or os.environ.get("ADMIN_SECRET", "").strip()
    )
    if secret:
        return secret
    if get_database_url():
        print(
            "[Auty] WARNING: JWT_SECRET not set; using insecure dev default. "
            "Set JWT_SECRET in production."
        )
        return "auty-dev-insecure-jwt-secret-change-me"
    return "auty-local-no-db"


def create_jwt(tenant_id: uuid.UUID, username: str) -> tuple[str, datetime]:
    """Return (token, expires_at_utc)."""
    expires_at = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "tenant_id": str(tenant_id),
        "sub": username,
        "exp": expires_at,
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)
    return token, expires_at


def decode_jwt(token: str) -> uuid.UUID:
    """Validate JWT and return tenant_id."""
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
        tenant_id = payload.get("tenant_id")
        if not tenant_id:
            raise JWTError("missing tenant_id")
        return uuid.UUID(str(tenant_id))
    except (JWTError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


def get_default_tenant_id() -> uuid.UUID:
    """First tenant in DB (bootstrap default). Cached."""
    global _default_tenant_id
    if _default_tenant_id is not None:
        return _default_tenant_id
    db = get_session_factory()()
    try:
        tenant = db.scalar(select(Tenant).order_by(Tenant.created_at).limit(1))
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No tenant configured",
            )
        _default_tenant_id = tenant.id
        return tenant.id
    finally:
        db.close()


def resolve_tenant(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> uuid.UUID:
    """Return tenant_id from JWT, or default tenant when Bearer is omitted."""
    if not get_database_url():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured",
        )
    if credentials is not None and credentials.scheme.lower() == "bearer":
        tenant_id = decode_jwt(credentials.credentials)
    else:
        tenant_id = get_default_tenant_id()
    set_current_tenant(tenant_id)
    return tenant_id


def optional_tenant(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[uuid.UUID]:
    """None when DATABASE_URL unset; otherwise same as resolve_tenant."""
    if not get_database_url():
        return None
    if credentials is not None and credentials.scheme.lower() == "bearer":
        tenant_id = decode_jwt(credentials.credentials)
    else:
        tenant_id = get_default_tenant_id()
    set_current_tenant(tenant_id)
    return tenant_id


def get_current_tenant(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> uuid.UUID:
    """FastAPI dependency: Bearer JWT required."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    tenant_id = decode_jwt(credentials.credentials)
    set_current_tenant(tenant_id)
    return tenant_id


def verify_admin_secret(admin_secret: str) -> None:
    """Validate ADMIN_SECRET header value."""
    expected = os.environ.get("ADMIN_SECRET", "").strip()
    if not expected or admin_secret.strip() != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing admin secret",
        )


def authenticate_tenant(
    db: Session, username: str, password: str
) -> Optional[Tenant]:
    """Look up tenant by username and verify password."""
    tenant = db.scalar(select(Tenant).where(Tenant.username == username.strip()))
    if tenant is None:
        return None
    if not verify_password(password, tenant.password_hash):
        return None
    return tenant
