"""End-to-end tests for /api/stats.

Skipped unless RUN_E2E=1 since the aggregations rely on Postgres-only
features (`unnest`, `date_trunc`) that SQLite can't run.
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

if os.environ.get("RUN_E2E") != "1":  # pragma: no cover
    pytest.skip("E2E suite skipped (set RUN_E2E=1)", allow_module_level=True)


from app.db import _engine, init_db
from app.main import app
from app.middleware import ratelimit

client = TestClient(app)


@pytest.fixture(autouse=True)
def _prepare_db():
    init_db()
    with _engine.begin() as conn:
        conn.execute(text("DELETE FROM recommendations"))
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(text("DELETE FROM users"))
    ratelimit.reset()
    yield


def _email() -> str:
    return f"stats-{uuid.uuid4().hex[:8]}@example.com"


def _fake_llm_in_place(monkeypatch, *, risk: str, mitre: list[str]) -> None:
    import app.services.llm as llm_module
    from app.services.llm import LLMAdapter

    class FakeLLM(LLMAdapter):
        def generate_json(self, prompt, *, schema, system=None, temperature=0.2, model=None):
            return {
                "summary": "x",
                "risk_level": risk,
                "mitre_techniques": mitre,
                "reasoning": "y",
            }

        def generate_text(self, prompt, *, system=None, temperature=0.2, model=None):
            return "x"

        def embed(self, texts):
            return [[0.0]]

    monkeypatch.setattr(llm_module, "_singleton", FakeLLM())


def test_stats_requires_auth():
    r = client.get("/api/stats")
    assert r.status_code == 401


def test_stats_empty_for_fresh_analyst(monkeypatch):
    _fake_llm_in_place(monkeypatch, risk="low", mitre=[])
    pw = "Stats-Pw-123456!"
    # First user → admin, second → analyst (so we can hit the analyst branch)
    client.post("/api/auth/register", json={"name": "A", "email": _email(), "password": pw})
    analyst_email = _email()
    client.post(
        "/api/auth/register",
        json={"name": "B", "email": analyst_email, "password": pw},
    )
    ratelimit.reset()
    c = TestClient(app)
    c.post("/api/auth/login", json={"email": analyst_email, "password": pw})

    r = c.get("/api/stats")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope"] == "self"
    assert body["totals"]["alerts"] == 0
    assert body["totals"]["recommendations"] == 0
    assert body["totals"]["users"] is None
    assert body["by_risk"] == []
    assert body["top_mitre"] == []
    assert body["daily_last_30d"] == []
    assert body["by_user"] is None


def test_stats_ownership_isolation(monkeypatch):
    _fake_llm_in_place(monkeypatch, risk="high", mitre=["T1110", "T1078"])
    pw = "Stats-Pw-123456!"
    admin_email = _email()
    a_email = _email()
    b_email = _email()
    for email in [admin_email, a_email, b_email]:
        client.post(
            "/api/auth/register",
            json={"name": "U", "email": email, "password": pw},
        )

    ratelimit.reset()

    def _login(email: str) -> TestClient:
        c = TestClient(app)
        r = c.post("/api/auth/login", json={"email": email, "password": pw})
        assert r.status_code == 200
        return c

    ca = _login(a_email)
    ca.post("/api/explain", json={"log": "alert from A 1"})
    ca.post("/api/explain", json={"log": "alert from A 2"})

    cb = _login(b_email)
    cb.post("/api/explain", json={"log": "alert from B 1"})

    # Analyst A: only their 2 alerts
    sa = ca.get("/api/stats").json()
    assert sa["scope"] == "self"
    assert sa["totals"]["alerts"] == 2
    # Each alert has 2 mitre techniques → top_mitre counts double
    counts_a = {m["technique"]: m["count"] for m in sa["top_mitre"]}
    assert counts_a == {"T1110": 2, "T1078": 2}
    risk_a = {b["risk_level"]: b["count"] for b in sa["by_risk"]}
    assert risk_a == {"high": 2}

    # Analyst B: only their 1 alert
    sb = cb.get("/api/stats").json()
    assert sb["totals"]["alerts"] == 1

    # Admin: sees all 3 alerts + per-user breakdown + users count
    cadmin = _login(admin_email)
    sadmin = cadmin.get("/api/stats").json()
    assert sadmin["scope"] == "all"
    assert sadmin["totals"]["alerts"] == 3
    assert sadmin["totals"]["users"] == 3
    counts_admin = {m["technique"]: m["count"] for m in sadmin["top_mitre"]}
    assert counts_admin == {"T1110": 3, "T1078": 3}
    by_user = {row["email"]: row["alerts"] for row in sadmin["by_user"]}
    assert by_user[a_email] == 2
    assert by_user[b_email] == 1
    # Admin themselves created no alerts → not in the join
    assert admin_email not in by_user


def test_stats_daily_bucket(monkeypatch):
    """Single-day creation collapses into one daily point."""
    _fake_llm_in_place(monkeypatch, risk="medium", mitre=["T1059"])
    pw = "Stats-Pw-123456!"
    admin_email = _email()
    client.post(
        "/api/auth/register",
        json={"name": "A", "email": admin_email, "password": pw},
    )
    ratelimit.reset()
    c = TestClient(app)
    c.post("/api/auth/login", json={"email": admin_email, "password": pw})
    for _ in range(3):
        c.post("/api/explain", json={"log": "same-day alert"})

    body = c.get("/api/stats").json()
    assert len(body["daily_last_30d"]) == 1
    assert body["daily_last_30d"][0]["count"] == 3
