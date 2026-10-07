"""End-to-end quota wall test.

Covers the full path: analyst burns the daily server-key budget, gets a
429 with a clear remediation hint, an admin clicks the reset endpoint, and
the analyst can keep going.

Skipped unless RUN_E2E=1 (matches the rest of the e2e suite) since it
needs Postgres and full ``init_db()``.
"""
from __future__ import annotations

import os
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
from app.services.llm import LLMAdapter

client = TestClient(app)


class _FakeQuotaLLM(LLMAdapter):
    """Stand-in adapter — never hits Gemini, always returns a valid
    ExplainResponse payload so /api/explain reaches the quota gate."""

    def generate_json(self, prompt, *, schema, system=None, temperature=0.2, model=None):
        return {
            "summary": "fake",
            "risk_level": "low",
            "mitre_techniques": [],
            "reasoning": "fake",
        }

    def generate_text(self, prompt, *, system=None, temperature=0.2, model=None):
        return "fake"

    def embed(self, texts):
        return [[0.0] for _ in texts]


@pytest.fixture(autouse=True)
def _prepare_db():
    init_db()
    with _engine.begin() as conn:
        conn.execute(text("DELETE FROM recommendations"))
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(text("DELETE FROM audit_logs"))
        conn.execute(text("DELETE FROM users"))
    ratelimit.reset()
    yield


def _email() -> str:
    return f"quota-{uuid.uuid4().hex[:8]}@example.com"


def test_quota_wall_then_admin_reset(monkeypatch):
    # Tighten the budget to keep the test snappy and re-cache settings.
    monkeypatch.setenv("SERVER_LLM_DAILY_QUOTA", "3")
    # Generous enough not to interfere — the auth bucket is the strict one.
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1000")
    get_settings.cache_clear()
    quota = get_settings().server_llm_daily_quota
    assert quota == 3

    # Replace the shared-key adapter so /api/explain is offline-deterministic.
    import app.services.llm as llm_module

    monkeypatch.setattr(llm_module, "_singleton", _FakeQuotaLLM())

    admin_email = _email()
    analyst_email = _email()
    pw = "Quota-Strong-Pw-1234!"

    # First user → admin, second → analyst (bootstrap rule).
    for email in (admin_email, analyst_email):
        r = client.post(
            "/api/auth/register",
            json={"name": "U", "email": email, "password": pw},
        )
        assert r.status_code == 201, r.text

    # Auth bucket is module-global; the two registers above ate into it.
    ratelimit.reset()

    # Login as the analyst and burn the budget.
    analyst = TestClient(app)
    r = analyst.post(
        "/api/auth/login", json={"email": analyst_email, "password": pw}
    )
    assert r.status_code == 200, r.text

    for i in range(quota):
        r = analyst.post("/api/explain", json={"log": f"alert {i}"})
        assert r.status_code == 200, f"call {i} failed: {r.text}"

    # Next call must trip the wall.
    r = analyst.post("/api/explain", json={"log": "one too many"})
    assert r.status_code == 429, r.text
    assert "Configure your own Gemini API key" in r.text

    # Admin logs in and resets the quota for the analyst.
    admin = TestClient(app)
    r = admin.post(
        "/api/auth/login", json={"email": admin_email, "password": pw}
    )
    assert r.status_code == 200, r.text

    me = admin.get("/api/auth/me").json()
    assert me["role"] == "admin"

    # Find the analyst id via the admin user list (also exercises AdminUserView).
    r = admin.get("/api/admin/users")
    assert r.status_code == 200, r.text
    rows = r.json()
    analyst_row = next(u for u in rows if u["email"] == analyst_email)
    assert analyst_row["server_llm_calls_today"] == quota
    assert analyst_row["server_llm_quota_limit"] == quota
    assert analyst_row["byo_key_configured"] is False

    r = admin.post(f"/api/admin/users/{analyst_row['id']}/reset-llm-quota")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["status"] == "ok"
    assert payload["user_id"] == analyst_row["id"]
    assert payload["previous_count"] >= quota

    # Analyst can call again right after the reset.
    r = analyst.post("/api/explain", json={"log": "back in business"})
    assert r.status_code == 200, r.text

    # And the admin view reflects the reset (counter back to 1 — the call we
    # just made consumed one).
    rows = admin.get("/api/admin/users").json()
    analyst_row = next(u for u in rows if u["email"] == analyst_email)
    assert analyst_row["server_llm_calls_today"] == 1
