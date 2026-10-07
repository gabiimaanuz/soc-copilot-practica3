"""End-to-end auth + ownership flow against a real Postgres.

Skipped automatically unless RUN_E2E=1 is exported, so the unit suite
keeps running offline. CI sets RUN_E2E=1 plus the standard POSTGRES_*
env vars and brings up a postgres service alongside.
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

if os.environ.get("RUN_E2E") != "1":  # pragma: no cover
    pytest.skip("E2E suite skipped (set RUN_E2E=1)", allow_module_level=True)


# Importing main triggers init_db() against the live DB.
from app.db import _engine, init_db
from app.main import app
from app.middleware import ratelimit

client = TestClient(app)


@pytest.fixture(autouse=True)
def _prepare_db():
    """Per-test wipe so each test starts on a clean slate (the
    'first user becomes admin' rule depends on row counts)."""
    init_db()
    with _engine.begin() as conn:
        conn.execute(text("DELETE FROM recommendations"))
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(text("DELETE FROM users"))
    # Auth bucket is module-global; clear so prior test's burst doesn't
    # blow the strict 5/min auth quota in the next test.
    ratelimit.reset()
    yield


def _email() -> str:
    return f"e2e-{uuid.uuid4().hex[:8]}@example.com"


def test_first_user_becomes_admin_and_full_flow():
    admin_email = _email()
    admin_pw = "Adminpass-Strong-12345!"

    # Register → first user is admin
    r = client.post(
        "/api/auth/register",
        json={"name": "Admin", "email": admin_email, "password": admin_pw},
    )
    assert r.status_code == 201, r.text
    assert r.json()["user"]["role"] == "admin"

    # Wrong password rejected
    r = client.post(
        "/api/auth/login",
        json={"email": admin_email, "password": "wrong-password"},
    )
    assert r.status_code == 401

    # Correct login sets the cookie
    r = client.post(
        "/api/auth/login",
        json={"email": admin_email, "password": admin_pw},
    )
    assert r.status_code == 200
    assert "soc_session" in r.cookies

    # Cookie is httpOnly + SameSite Lax
    set_cookie = r.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()

    # /me works with the cookie session
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == admin_email

    # Second register → analyst role
    analyst_email = _email()
    analyst_pw = "Analystpass-Xyz-9999!"
    r = client.post(
        "/api/auth/register",
        json={"name": "Analyst", "email": analyst_email, "password": analyst_pw},
    )
    assert r.status_code == 201
    assert r.json()["user"]["role"] == "analyst"

    # Logout invalidates the cookie session
    r = client.post("/api/auth/logout")
    assert r.status_code == 204
    r = client.get("/api/auth/me")
    assert r.status_code == 401


# ─── Registration hardening (Phase 6) ───────────────────────────────────


def test_register_rejects_duplicate_email():
    """Second register with the same email returns 409."""
    pw = "Dup-Strong-Pass!-1234"
    e = _email()
    r1 = client.post(
        "/api/auth/register",
        json={"name": "First", "email": e, "password": pw},
    )
    assert r1.status_code == 201, r1.text
    r2 = client.post(
        "/api/auth/register",
        json={"name": "Second", "email": e, "password": pw},
    )
    assert r2.status_code == 409
    assert "registered" in r2.json()["detail"].lower()


def test_register_rejects_weak_password_at_http_layer():
    r = client.post(
        "/api/auth/register",
        json={"name": "Weak", "email": _email(), "password": "weakpass"},
    )
    # Pydantic validator → 422.
    assert r.status_code == 422


def test_check_email_endpoint():
    e = _email()
    r = client.get(f"/api/auth/check-email?email={e}")
    assert r.status_code == 200
    assert r.json() == {"available": True}

    pw = "Check-Email-Strong-1!"
    client.post(
        "/api/auth/register",
        json={"name": "Owner", "email": e, "password": pw},
    )
    r = client.get(f"/api/auth/check-email?email={e}")
    assert r.json() == {"available": False}


def test_login_locks_after_threshold_failures():
    """4 failed attempts → account locked; correct password still rejected."""
    from app.config import get_settings
    from app.middleware import ratelimit as rl

    settings = get_settings()
    threshold = settings.auth_lockout_threshold

    email = _email()
    pw = "Locked-Out-Strong-1!"
    r = client.post(
        "/api/auth/register",
        json={"name": "Lockee", "email": email, "password": pw},
    )
    assert r.status_code == 201, r.text

    # Burn through the strict auth bucket allowance carefully — reset
    # between attempts so the rate limiter doesn't 429 us before we hit
    # the lockout threshold.
    for _ in range(threshold):
        rl.reset()
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": "wrong-password"},
        )
        assert r.status_code == 401, r.text

    # Right password now also rejected (same opaque 401).
    rl.reset()
    r = client.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 401, r.text

    # Audit log captured the lockout.
    admin_email = _email()
    admin_pw = "Audit-Admin-Strong-1!"
    rl.reset()
    # Need an admin to read the audit endpoint; register one (this is
    # actually the second user → analyst because Lockee was first… so
    # bootstrap one BEFORE the lockout block).
    # Instead, just check the audit table directly.
    from sqlalchemy import select, text  # noqa: F401
    from app.db import _SessionLocal
    from app.models import AuditLog

    with _SessionLocal() as s:
        rows = s.scalars(
            select(AuditLog).where(AuditLog.action == "auth.lockout")
        ).all()
        assert any(r.target_label == email for r in rows), [
            (r.action, r.target_label) for r in rows
        ]
    _ = (admin_email, admin_pw)


def test_verification_required_blocks_login_until_token_used(monkeypatch):
    """With email verification on, a fresh non-bootstrap user must verify
    before /auth/login succeeds."""
    from app.config import Settings, get_settings
    from app.middleware import ratelimit as rl

    # Bootstrap an admin first (auto-verified).
    admin_pw = "Verif-Admin-Strong-1!"
    admin_email = _email()
    r = client.post(
        "/api/auth/register",
        json={"name": "Admin", "email": admin_email, "password": admin_pw},
    )
    assert r.status_code == 201, r.text
    assert r.json()["user"]["is_verified"] is True

    # Flip the gate on for the second user.
    def _patched():
        s = Settings()
        s.auth_require_email_verification = True
        return s

    get_settings.cache_clear()
    monkeypatch.setattr("app.routers.auth.get_settings", _patched)

    rl.reset()
    user_email = _email()
    user_pw = "Verif-User-Strong-1!"
    r = client.post(
        "/api/auth/register",
        json={"name": "U", "email": user_email, "password": user_pw},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["verification_required"] is True
    assert body["user"]["is_verified"] is False
    link = body["verification_link_dev"]
    assert link and "token=" in link

    # Login refused until verified.
    rl.reset()
    r = client.post(
        "/api/auth/login", json={"email": user_email, "password": user_pw}
    )
    assert r.status_code == 403, r.text

    # Verify with the token.
    token = link.split("token=", 1)[1]
    r = client.post("/api/auth/verify-email", json={"token": token})
    assert r.status_code == 200, r.text
    assert r.json()["is_verified"] is True

    # Now login works.
    rl.reset()
    r = client.post(
        "/api/auth/login", json={"email": user_email, "password": user_pw}
    )
    assert r.status_code == 200, r.text

    # Re-using the same token → 400 (single-use).
    rl.reset()
    r = client.post("/api/auth/verify-email", json={"token": token})
    assert r.status_code == 400

    get_settings.cache_clear()


def test_verification_token_expired():
    """A stale token (older than TTL) is rejected with the same opaque
    error as an unknown token."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select
    from app.config import get_settings
    from app.db import _SessionLocal
    from app.models import User
    from app.middleware import ratelimit as rl
    from app.services.auth import generate_verification_token

    # Bootstrap admin → auto-verified; we need a SECOND user to inject a
    # stale token into.
    admin_pw = "Exp-Admin-Strong-1!"
    client.post(
        "/api/auth/register",
        json={"name": "A", "email": _email(), "password": admin_pw},
    )
    rl.reset()

    user_email = _email()
    user_pw = "Exp-User-Strong-1!"
    r = client.post(
        "/api/auth/register",
        json={"name": "U", "email": user_email, "password": user_pw},
    )
    assert r.status_code == 201

    # Force a stale token on this user.
    settings = get_settings()
    stale_token = generate_verification_token()
    with _SessionLocal() as s:
        u = s.scalar(select(User).where(User.email == user_email))
        u.is_verified = False
        u.email_verified_at = None
        u.email_verification_token = stale_token
        u.email_verification_sent_at = datetime.now(UTC) - timedelta(
            hours=settings.email_verification_ttl_hours + 1
        )
        s.commit()

    rl.reset()
    r = client.post("/api/auth/verify-email", json={"token": stale_token})
    assert r.status_code == 400
    assert "expirado" in r.json()["detail"].lower() or "invalid" in r.json()["detail"].lower()


def test_ownership_isolation_between_users(monkeypatch):
    """Two analysts each see only their own alerts; admin sees both."""
    # Create three users
    admin_email = _email()
    a_email = _email()
    b_email = _email()
    pw = "Shared-Strong-Pw-1234!"
    for email in [admin_email, a_email, b_email]:
        r = client.post(
            "/api/auth/register",
            json={"name": "User", "email": email, "password": pw},
        )
        assert r.status_code == 201, r.text

    # Inject a fake LLM so /api/explain succeeds without hitting Gemini.
    import app.services.llm as llm_module
    from app.services.llm import LLMAdapter

    class FakeLLM(LLMAdapter):
        def generate_json(self, prompt, *, schema, system=None, temperature=0.2, model=None):
            return {
                "summary": "x",
                "risk_level": "low",
                "mitre_techniques": [],
                "reasoning": "y",
            }

        def generate_text(self, prompt, *, system=None, temperature=0.2, model=None):
            return "x"

        def embed(self, texts):
            return [[0.0]]

    monkeypatch.setattr(llm_module, "_singleton", FakeLLM())

    def _login(email: str) -> TestClient:
        c = TestClient(app)
        r = c.post("/api/auth/login", json={"email": email, "password": pw})
        assert r.status_code == 200, r.text
        return c

    # The 3 registers above already consumed most of the strict 5/min auth
    # bucket. Reset before the 3 logins below so we don't trip the limiter
    # mid-test (the autouse fixture only resets between tests).
    ratelimit.reset()

    # Each analyst creates one alert
    ca = _login(a_email)
    rA = ca.post("/api/explain", json={"log": "alert A"}).json()
    cb = _login(b_email)
    rB = cb.post("/api/explain", json={"log": "alert B"}).json()
    assert rA["id"] != rB["id"]

    # Analyst A only sees A's alert
    listed = ca.get("/api/alerts?limit=50").json()
    ids = {a["id"] for a in listed}
    assert rA["id"] in ids
    assert rB["id"] not in ids

    # Analyst A cannot read B's alert (404, not 403, to avoid existence leak)
    detail = ca.get(f"/api/alerts/{rB['id']}")
    assert detail.status_code == 404

    # Admin sees both
    cadmin = _login(admin_email)
    listed_admin = cadmin.get("/api/alerts?limit=50").json()
    ids_admin = {a["id"] for a in listed_admin}
    assert rA["id"] in ids_admin and rB["id"] in ids_admin
