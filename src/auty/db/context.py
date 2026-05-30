"""Request-scoped tenant context for dual-write from the vision pipeline."""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Optional

current_tenant_id: ContextVar[Optional[uuid.UUID]] = ContextVar(
    "current_tenant_id", default=None
)


def set_current_tenant(tenant_id: Optional[uuid.UUID]) -> None:
    current_tenant_id.set(tenant_id)


def get_current_tenant_context() -> Optional[uuid.UUID]:
    return current_tenant_id.get()
