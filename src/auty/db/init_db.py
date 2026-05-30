"""Create database tables if they do not exist."""

from __future__ import annotations

from auty.db.connection import get_engine
from auty.db.models import Base


def create_all_tables() -> None:
    """Idempotent: creates any missing tables from SQLAlchemy metadata."""
    Base.metadata.create_all(bind=get_engine())
