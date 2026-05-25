"""
Biometric consent management.

Every employee must complete the consent flow before face data is captured.
Consent records are stored in data/consent_log.json.  The form version is
bumped when the privacy policy changes — employees with an older version
are required to re-consent before their next enrollment.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Dict, Optional

from utils.time_utils import utc_now_iso as _utc_now_iso


class ConsentManager:
    def __init__(self, *, log_path: str, form_version: str = "1.0"):
        self._log_path = log_path
        self._current_version = form_version
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

    def check_consent(self, employee_id: str) -> bool:
        """Return True if the employee has given valid consent for the current form version."""
        record = self.get_consent(employee_id)
        if record is None:
            return False
        if not record.get("consent_given", False):
            return False
        return record.get("form_version", "") == self._current_version

    def get_consent(self, employee_id: str) -> Optional[dict]:
        """Return the most recent consent record for this employee, or None."""
        records = self._load()
        return records.get(employee_id)

    def record_consent(
        self,
        *,
        employee_id: str,
        name: str,
        ip_address: str = "unknown",
        form_version: Optional[str] = None,
    ) -> dict:
        version = form_version or self._current_version
        record = {
            "employee_id": employee_id,
            "name": name,
            "timestamp_utc": _utc_now_iso(),
            "ip_address": ip_address,
            "form_version": version,
            "consent_given": True,
        }
        with self._lock:
            records = self._load()
            records[employee_id] = record
            self._save(records)
        return record

    def revoke_consent(self, employee_id: str) -> bool:
        with self._lock:
            records = self._load()
            if employee_id not in records:
                return False
            records[employee_id]["consent_given"] = False
            records[employee_id]["revoked_at"] = _utc_now_iso()
            self._save(records)
        return True

    def request_deletion(self, employee_id: str) -> dict:
        """Mark an employee's data for deletion and return a request record."""
        record = {
            "employee_id": employee_id,
            "deletion_requested_at": _utc_now_iso(),
            "status": "pending",
        }
        with self._lock:
            records = self._load()
            existing = records.get(employee_id, {})
            existing["deletion_request"] = record
            existing["consent_given"] = False
            records[employee_id] = existing
            self._save(records)
        return record

    def _load(self) -> Dict[str, dict]:
        try:
            with open(self._log_path, "r") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, records: Dict[str, dict]):
        with open(self._log_path, "w") as f:
            json.dump(records, f, indent=2)
