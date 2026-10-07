"""E2E: forgot password → emailed link → new password. Needs RUN_E2E=1.

Runs with MFA_REQUIRED=false (like the other password-only e2e tests).
SMTP is not configured in CI, so the API returns the link in
``reset_link_dev`` (development only).
"""
from __future__ import annotations

import os
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

if os.environ.get("RUN_E2E") != "1":  # pragma: no cover
    pytest.skip("E2E suite skipped (set RUN_E2E=1)", allow_module_level=True)

from app.config import get_settings
from app.db import _engine, init_db
from app.main import app
from app.middleware import ratelimit

OLD = "Old-Strong-Password-123!"
NEW = "New-Strong-Password-456!"


@pytest.fixture(autouse=True)
def _prepare(monkeypatch):
    init_db()
    with _engine.begin() as conn:
        conn.execute(text("DELETE FROM recommendations"))
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(text("DELETE FROM users"))
    ratelimit.reset()
    monkeypatch.setattr(get_settings(), "mfa_required", False)
    monkeypatch.setattr(get_settings(), "smtp_host", "")
    yield


def test_full_password_reset_flow():
    c = TestClient(app)
    email = f"reset-{uuid.uuid4().hex[:8]}@example.com"
    assert c.post(
        "/api/auth/register", json={"name": "Ana", "email": email, "password": OLD}
    ).status_code == 201
    ratelimit.reset()
    assert c.post("/api/auth/login", json={"email": email, "password": OLD}).status_code == 200

    r = c.post("/api/auth/forgot-password", json={"email": email})
    assert r.status_code == 202
    link = r.json()["reset_link_dev"]
    assert link and "/reset-password?token=" in link
    token = parse_qs(urlparse(link).query)["token"][0]

    ratelimit.reset()
    assert c.post(
        "/api/auth/reset-password", json={"token": token, "new_password": NEW}
    ).status_code == 204

    # Old session invalidated, old password rejected, new one works.
    assert c.get("/api/auth/me").status_code == 401
    assert c.post("/api/auth/login", json={"email": email, "password": OLD}).status_code == 401
    ratelimit.reset()
    assert c.post("/api/auth/login", json={"email": email, "password": NEW}).status_code == 200

    # Token is single use.
    ratelimit.reset()
    assert c.post(
        "/api/auth/reset-password", json={"token": token, "new_password": OLD}
    ).status_code == 400
