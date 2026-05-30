#!/usr/bin/env python3
"""
Phase 6 — automated multi-tenant isolation checks.

Requires PostgreSQL (DATABASE_URL) and env:
  ADMIN_SECRET, JWT_SECRET (recommended)

Optional: starts checks against FastAPI app in-process (no running server).

Usage:
  export DATABASE_URL=postgresql://...
  export ADMIN_SECRET=test-admin-secret
  export JWT_SECRET=test-jwt-secret
  python scripts/verify_multitenant.py
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

import numpy as np

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

# Defer heavy vision boot during API tests
os.environ.setdefault("AUTY_DEFER_VISION_BOOT", "1")
os.environ.setdefault("RAILWAY_ENVIRONMENT", "1")

from sqlalchemy import func, select

from auty.db.connection import get_database_url, get_session_factory
from auty.db.embedding_store import load_tenant_gallery, save_embeddings
from auty.db.init_db import create_all_tables
from auty.db.models import Attendance, Employee, Embedding, Tenant
from auty.db.repositories import list_employees


class CheckResult:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.skipped: list[str] = []

    def ok(self, name: str) -> None:
        self.passed.append(name)
        print(f"  PASS  {name}")

    def fail(self, name: str, detail: str = "") -> None:
        msg = f"{name}" + (f": {detail}" if detail else "")
        self.failed.append(msg)
        print(f"  FAIL  {msg}")

    def skip(self, name: str, reason: str) -> None:
        self.skipped.append(f"{name} ({reason})")
        print(f"  SKIP  {name} — {reason}")


def _admin_headers() -> dict[str, str]:
    secret = os.environ.get("ADMIN_SECRET", "").strip()
    if not secret:
        raise RuntimeError("ADMIN_SECRET is required for tenant creation tests")
    return {"ADMIN_SECRET": secret}


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_tenant(client, username: str, password: str) -> dict:
    r = client.post(
        "/api/admin/tenants",
        json={"name": f"Test {username}", "username": username, "password": password},
        headers=_admin_headers(),
    )
    if r.status_code == 409:
        # Already exists — log in instead
        login = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        if login.status_code != 200:
            raise RuntimeError(f"login failed for existing tenant {username}: {login.text}")
        return {"username": username, "token": login.json()["token"], "id": None}
    if r.status_code != 200:
        raise RuntimeError(f"create tenant {username}: {r.status_code} {r.text}")
    body = r.json()
    login = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    if login.status_code != 200:
        raise RuntimeError(f"login failed for {username}: {login.text}")
    return {
        "id": body["id"],
        "username": username,
        "token": login.json()["token"],
    }


def _seed_employee(db, tenant_id: uuid.UUID, name: str) -> uuid.UUID:
    eid = uuid.uuid5(tenant_id, f"verify:{name}")
    existing = db.scalar(
        select(Employee).where(Employee.tenant_id == tenant_id, Employee.id == eid)
    )
    if existing is None:
        db.add(
            Employee(
                id=eid,
                tenant_id=tenant_id,
                name=name,
                status="FRIEND",
                enrolled_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    vec = np.zeros(512, dtype=np.float32)
    vec[hash(name) % 512] = 1.0
    save_embeddings(db, eid, tenant_id, [vec])
    return eid


def _tenant_uuid(db, username: str) -> Optional[uuid.UUID]:
    return db.scalar(select(Tenant.id).where(Tenant.username == username))


def run_checks() -> CheckResult:
    from fastapi.testclient import TestClient

    from server.main import app

    result = CheckResult()
    create_all_tables()

    with TestClient(app) as client:
        # 1. Create two tenants
        try:
            ta = _create_tenant(client, "phase6_tenant_a", "pass-a-1234")
            tb = _create_tenant(client, "phase6_tenant_b", "pass-b-5678")
            result.ok("Create two tenants via POST /api/admin/tenants (+ login)")
        except Exception as exc:
            result.fail("Create two tenants", str(exc))
            return result

        db = get_session_factory()()
        try:
            tid_a = _tenant_uuid(db, "phase6_tenant_a")
            tid_b = _tenant_uuid(db, "phase6_tenant_b")
            if tid_a is None or tid_b is None:
                result.fail("Resolve tenant IDs from database")
                return result

            # 2. Seed employees + embeddings per tenant
            _seed_employee(db, tid_a, "Alice-A")
            _seed_employee(db, tid_b, "Bob-B")
            result.ok("Seed employees + embeddings per tenant (DB)")

            # 3. GET /api/profiles isolation
            prof_a = client.get("/api/profiles", headers=_auth_headers(ta["token"]))
            prof_b = client.get("/api/profiles", headers=_auth_headers(tb["token"]))
            names_a = {p["name"] for p in prof_a.json()}
            names_b = {p["name"] for p in prof_b.json()}
            if "Alice-A" in names_a and "Bob-B" not in names_a:
                if "Bob-B" in names_b and "Alice-A" not in names_b:
                    result.ok("GET /api/profiles returns only that tenant's employees")
                else:
                    result.fail("GET /api/profiles tenant B", f"names={names_b}")
            else:
                result.fail("GET /api/profiles tenant A", f"names={names_a}")

            # 4. Attendance isolation
            ev_a = uuid.uuid4()
            ev_b = uuid.uuid4()
            if db.scalar(select(Attendance.id).where(Attendance.id == ev_a)) is None:
                db.add(
                    Attendance(
                        id=ev_a,
                        tenant_id=tid_a,
                        employee_name="Alice-A",
                        event="CLOCK_IN",
                        timestamp_ts=datetime.now(timezone.utc).timestamp(),
                        location_id="main",
                        created_at=datetime.now(timezone.utc),
                    )
                )
            if db.scalar(select(Attendance.id).where(Attendance.id == ev_b)) is None:
                db.add(
                    Attendance(
                        id=ev_b,
                        tenant_id=tid_b,
                        employee_name="Bob-B",
                        event="CLOCK_IN",
                        timestamp_ts=datetime.now(timezone.utc).timestamp(),
                        location_id="main",
                        created_at=datetime.now(timezone.utc),
                    )
                )
            db.commit()

            events_a = client.get(
                "/api/attendance/events", headers=_auth_headers(ta["token"])
            ).json()
            events_b = client.get(
                "/api/attendance/events", headers=_auth_headers(tb["token"])
            ).json()
            a_names = {e.get("name") for e in events_a}
            b_names = {e.get("name") for e in events_b}
            if "Bob-B" not in a_names and "Alice-A" in a_names:
                if "Alice-A" not in b_names and "Bob-B" in b_names:
                    result.ok("Attendance events isolated per tenant")
                else:
                    result.fail("Attendance tenant B", f"names={b_names}")
            else:
                result.fail("Attendance tenant A", f"names={a_names}")

            # 5. Recognition gallery isolation
            gal_a = load_tenant_gallery(db, tid_a)
            gal_b = load_tenant_gallery(db, tid_b)
            if "Alice-A" in gal_a and "Bob-B" not in gal_a:
                if "Bob-B" in gal_b and "Alice-A" not in gal_b:
                    from vision.matcher import match_identity

                    vec_a = gal_a["Alice-A"][0]
                    name_match, score, _, _ = match_identity(gal_a, vec_a)
                    cross, cross_score, _, _ = match_identity(gal_b, vec_a)
                    if name_match == "Alice-A" and cross == "UNKNOWN":
                        result.ok(
                            "Recognition gallery scoped per tenant (match_identity)"
                        )
                    else:
                        result.fail(
                            "Recognition gallery",
                            f"match={name_match} cross={cross} scores={score},{cross_score}",
                        )
                else:
                    result.fail("Gallery tenant B", str(list(gal_b.keys())))
            else:
                result.fail("Gallery tenant A", str(list(gal_a.keys())))

            # 6. Delete profile only within tenant
            alice_id = str(_seed_employee(db, tid_a, "Alice-Delete"))
            _seed_employee(db, tid_b, "Bob-Keep")
            del_r = client.delete(
                f"/api/profiles/{alice_id}",
                headers=_auth_headers(ta["token"]),
            )
            b_after = {
                p["name"]
                for p in client.get(
                    "/api/profiles", headers=_auth_headers(tb["token"])
                ).json()
            }
            if del_r.status_code == 200 and "Bob-Keep" in b_after:
                a_names_after = {
                    p["name"]
                    for p in client.get(
                        "/api/profiles", headers=_auth_headers(ta["token"])
                    ).json()
                }
                if "Alice-Delete" not in a_names_after:
                    result.ok("DELETE /api/profiles only affects current tenant")
                else:
                    result.fail("Delete tenant A", f"still has {a_names_after}")
            else:
                result.fail("DELETE /api/profiles", f"status={del_r.status_code}")

            # 7. reset-all only current tenant
            _seed_employee(db, tid_a, "Reset-A1")
            _seed_employee(db, tid_b, "Reset-B1")
            reset_r = client.post(
                "/api/profiles/reset-all", headers=_auth_headers(ta["token"])
            )
            count_b = db.scalar(
                select(func.count())
                .select_from(Employee)
                .where(Employee.tenant_id == tid_b)
            )
            count_a = db.scalar(
                select(func.count())
                .select_from(Employee)
                .where(Employee.tenant_id == tid_a)
            )
            if reset_r.status_code == 200 and int(count_b or 0) >= 1:
                if int(count_a or 0) == 0:
                    result.ok("POST /api/profiles/reset-all only resets current tenant")
                else:
                    result.fail("reset-all tenant A", f"remaining employees={count_a}")
            else:
                result.fail(
                    "reset-all",
                    f"status={reset_r.status_code} tenant_b_count={count_b}",
                )

            # 8. Migration — run manually on host with legacy data/
            from utils.paths import PROFILES_PATH

            if PROFILES_PATH.is_file():
                result.skip(
                    "migrate_to_postgres.py",
                    "run: python scripts/migrate_to_postgres.py (idempotent)",
                )
            else:
                result.skip(
                    "migrate_to_postgres.py",
                    "no local data/profiles.json on this machine",
                )

            # 9. E2E — manual
            result.skip(
                "End-to-end kiosk flow",
                "manual: login → enroll → kiosk → clock in → dashboard → export CSV",
            )

        finally:
            db.close()

    return result


def main() -> int:
    if not get_database_url():
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        print("\nManual Phase 6 checklist:", file=sys.stderr)
        checklist = [
            "Create two tenants: POST /api/admin/tenants (ADMIN_SECRET header)",
            "Login each tenant; enroll different employees",
            "GET /api/profiles — only that tenant's rows",
            "Clock events — isolated per tenant on dashboard",
            "Kiosk recognition — matches only same-tenant gallery",
            "DELETE /api/profiles/{id} — other tenant unchanged",
            "POST /api/profiles/reset-all — other tenant unchanged",
            "python scripts/migrate_to_postgres.py on deploy with legacy data",
            "Full flow: login → enroll → kiosk → clock in → export CSV",
        ]
        for i, line in enumerate(checklist, 1):
            print(f"  {i}. {line}", file=sys.stderr)
        return 1

    if not os.environ.get("ADMIN_SECRET", "").strip():
        print("ERROR: ADMIN_SECRET is required for automated tests.", file=sys.stderr)
        return 1

    print("[verify] Phase 6 multi-tenant checks\n")
    result = run_checks()

    print(f"\n[verify] {len(result.passed)} passed, {len(result.failed)} failed, {len(result.skipped)} skipped")
    if result.failed:
        for item in result.failed:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
