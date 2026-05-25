"""
Append-only audit log for admin actions.

Logged actions: enrollment, deletion, export, settings_change, manager_override,
consent, deletion_request.  Records are never modified — only appended.
"""

from __future__ import annotations

import json
import os
import threading
from collections import deque
from typing import List, Optional

from utils.time_utils import utc_now_iso as _utc_now_iso


class AuditLog:
    def __init__(self, *, log_path: str):
        self._log_path = log_path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

    def log(
        self,
        action: str,
        *,
        actor: str = "system",
        detail: str = "",
        extra: Optional[dict] = None,
    ) -> dict:
        entry = {
            "timestamp_utc": _utc_now_iso(),
            "action": action,
            "actor": actor,
            "detail": detail,
        }
        if extra:
            entry.update(extra)
        with self._lock:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        return entry

    def tail(self, limit: int = 50) -> List[dict]:
        """Return the most recent audit entries."""
        ring: deque[dict] = deque(maxlen=limit)
        try:
            with open(self._log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ring.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return []
        return list(ring)
