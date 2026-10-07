"""E2E: mandatory MFA (TOTP) against a real Postgres. Needs RUN_E2E=1.

The rest of the e2e suite runs with MFA_REQUIRED=false (test-only switch,
refused in production); this module forces it on.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

if os.environ.get("RUN_E2E") != "1":  # pragma: no cover
    pytest.skip("E2E suite skipped (set RUN_E2E=1)", allow_module_level=True)

from app.config import get_settings
from app.db import _engine, init_db
from app.main import app
from app.middleware import ratelimit
from app.services import mfa

PW = "Shared-Strong-Pw-1234!"


@pytest.fixture(autouse=True)
def _prepare(monkeypatch):
    init_db()
    with _engine.begin() as conn:
        conn.execute(text("DELETE FROM recommendations"))
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(text("DELETE FROM users"))
    ratelimit.reset()
    s = get_settings()
    monkeypatch.setattr(s, "mfa_required", True)
    if not s.app_encryption_key:
        monkeypatch.setattr(
            s, "app_encryption_key", "m24ERtIpLGYhHLZ_TeXqXnXRUZ9GlMM_hwdPTSCDPQM="
        )
    yield


def _register(c: TestClient) -> str:
    email = f"mfa-{uuid.uuid4().hex[:8]}@example.com"
    r = c.post("/api/auth/register", json={"name": "Ana", "email": email, "password": PW})
    assert r.status_code == 201, r.text
    return email


def test_full_mfa_flow():
    c = TestClient(app)
    email = _register(c)

    # 1) Password OK → no session yet, enrolment required.
    r = c.post("/api/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mfa_required"] and body["mfa_setup_required"] and body["user"] is None
    assert c.get("/api/auth/me").status_code == 401

    # 2) Setup → QR + secret.
    r = c.post("/api/auth/mfa/setup")
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    assert r.json()["qr_svg_data_uri"].startswith("data:image/svg+xml")

    # 3) Wrong code rejected.
    ratelimit.reset()
    assert c.post("/api/auth/mfa/verify", json={"code": "000000"}).status_code in (401,)

    # 4) Right code → session + 10 recovery codes (once).
    now = time.time()
    r = c.post("/api/auth/mfa/verify", json={"code": mfa.totp(secret, now)})
    assert r.status_code == 200, r.text
    rc = r.json()["recovery_codes"]
    assert len(rc) == 10
    me = c.get("/api/auth/me").json()
    assert me["mfa_enabled"] is True

    # 5) Second login with the NEXT step's code (same code would be a replay).
    c.post("/api/auth/logout")
    ratelimit.reset()
    r = c.post("/api/auth/login", json={"email": email, "password": PW})
    assert r.json()["mfa_setup_required"] is False
    r = c.post("/api/auth/mfa/verify", json={"code": mfa.hotp(secret, mfa.current_step(now) + 1)})
    assert r.status_code == 200, r.text
    assert r.json()["recovery_codes"] is None

    # 6) Recovery code login, single use.
    c.post("/api/auth/logout")
    ratelimit.reset()
    c.post("/api/auth/login", json={"email": email, "password": PW})
    r = c.post("/api/auth/mfa/verify", json={"recovery_code": rc[0]})
    assert r.status_code == 200 and r.json()["recovery_codes_left"] == 9
    c.post("/api/auth/logout")
    ratelimit.reset()
    c.post("/api/auth/login", json={"email": email, "password": PW})
    assert c.post("/api/auth/mfa/verify", json={"recovery_code": rc[0]}).status_code == 401


def test_admin_can_reset_mfa():
    admin = TestClient(app)
    admin_email = _register(admin)  # first user → admin
    ratelimit.reset()
    admin.post("/api/auth/login", json={"email": admin_email, "password": PW})
    secret = admin.post("/api/auth/mfa/setup").json()["secret"]
    assert admin.post(
        "/api/auth/mfa/verify", json={"code": mfa.totp(secret)}
    ).status_code == 200

    analyst = TestClient(app)
    ratelimit.reset()
    analyst_email = _register(analyst)
    ratelimit.reset()
    analyst.post("/api/auth/login", json={"email": analyst_email, "password": PW})
    s2 = analyst.post("/api/auth/mfa/setup").json()["secret"]
    analyst.post("/api/auth/mfa/verify", json={"code": mfa.totp(s2)})
    assert analyst.get("/api/auth/me").status_code == 200
    uid = analyst.get("/api/auth/me").json()["id"]

    r = admin.post(f"/api/admin/users/{uid}/mfa/reset")
    assert r.status_code == 200 and r.json()["was_enabled"] is True
    # Analyst's session is invalidated (password_version bumped)…
    assert analyst.get("/api/auth/me").status_code == 401
    # …and next login asks for enrolment again.
    ratelimit.reset()
    r = analyst.post("/api/auth/login", json={"email": analyst_email, "password": PW})
    assert r.json()["mfa_setup_required"] is True
