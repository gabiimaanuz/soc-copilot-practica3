"""E2E: Wazuh webhook → Postgres → shared triage queue → AI analysis.

Skipped unless RUN_E2E=1 (same as the rest of the e2e suite).
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

TOKEN = "w" * 40
URL = "/api/integrations/wazuh/webhook"
PW = "Shared-Strong-Pw-1234!"


def _alert(alert_id: str, level: int = 10) -> dict:
    return {
        "timestamp": "2026-10-05T10:11:12.345+0000",
        "id": alert_id,
        "rule": {
            "id": "5712",
            "level": level,
            "description": "sshd: brute force",
            "mitre": {"id": ["T1110"]},
        },
        "agent": {"id": "001", "name": "web-01", "ip": "10.0.0.5"},
        "full_log": "Failed password for invalid user admin from 1.2.3.4",
    }


@pytest.fixture(autouse=True)
def _prepare(monkeypatch):
    init_db()
    with _engine.begin() as conn:
        conn.execute(text("DELETE FROM recommendations"))
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(text("DELETE FROM users"))
    ratelimit.reset()
    monkeypatch.setattr(get_settings(), "wazuh_webhook_token", TOKEN)
    monkeypatch.setattr(get_settings(), "wazuh_min_rule_level", 7)
    yield


def test_webhook_ingests_dedupes_and_analyst_can_triage(monkeypatch):
    c = TestClient(app)
    hdr = {"Authorization": f"Bearer {TOKEN}"}
    aid = f"sim-{uuid.uuid4().hex[:8]}"

    r = c.post(URL, json=[_alert(aid), _alert(aid + "-low", level=3)], headers=hdr)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["created"] == 1 and body["below_threshold"] == 1

    # Same alert again (integratord retry / pull overlap) → duplicate.
    r = c.post(URL, json=_alert(aid), headers=hdr)
    assert r.json()["duplicates"] == 1 and r.json()["created"] == 0

    # Two users: first is admin, second analyst.
    admin_email = f"a-{uuid.uuid4().hex[:6]}@example.com"
    analyst_email = f"b-{uuid.uuid4().hex[:6]}@example.com"
    for e in (admin_email, analyst_email):
        assert c.post(
            "/api/auth/register", json={"name": "U", "email": e, "password": PW}
        ).status_code == 201
    ratelimit.reset()

    ca = TestClient(app)
    assert ca.post(
        "/api/auth/login", json={"email": analyst_email, "password": PW}
    ).status_code == 200

    queue = ca.get("/api/alerts?origin=wazuh&pending=true").json()
    assert len(queue) == 1
    item = queue[0]
    assert item["origin"] == "wazuh" and item["risk_level"] == "high"
    assert item["mitre_techniques"] == ["T1110"] and item["analyzed_at"] is None

    import app.services.llm as llm_module
    from app.services.llm import LLMAdapter

    class FakeLLM(LLMAdapter):
        def generate_json(self, prompt, *, schema, system=None, temperature=0.2, model=None):
            return {"summary": "ai", "risk_level": "critical",
                    "mitre_techniques": ["T1110.001"], "reasoning": "r"}

        def generate_text(self, prompt, *, system=None, temperature=0.2, model=None):
            return "x"

        def embed(self, texts):
            return [[0.0]]

    monkeypatch.setattr(llm_module, "_singleton", FakeLLM())
    r = ca.post(f"/api/alerts/{item['id']}/analyze", json={})
    assert r.status_code == 200, r.text
    assert r.json()["risk_level"] == "critical"
    assert r.json()["analyzed_at"] is not None

    assert ca.get("/api/alerts?origin=wazuh&pending=true").json() == []

    # Admin-only status endpoint.
    assert ca.get("/api/integrations/wazuh/status").status_code == 403
