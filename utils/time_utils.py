"""
Shared time helpers — used by attendance_tracker, audit_log, and consent_manager.
"""

from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
