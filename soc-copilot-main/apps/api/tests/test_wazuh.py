"""Wazuh integration — offline unit tests (no Postgres, no Wazuh).

Covers the pure normalisation logic, the webhook authentication and
payload handling (DB layer faked), and the alert visibility rules.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.middleware import ratelimit
from app.models import Alert, User, UserRole
from app.routers import integrations as integ_router
from app.services import wazuh
from app.services.alert_access import can_view_alert

SAMPLE = {
    "timestamp": "2026-10-05T10:11:12.345+0000",
    "id": "1728123072.123456",
    "rule": {
        "id": "5712",
        "level": 10,
        "description": "sshd: brute force trying to get access to the system.",
        "mitre": {"id": ["T1110"], "tactic": ["Credential Access"]},
    },
    "agent": {"id": "001", "name": "web-01", "ip": "10.0.0.5"},
    "decoder": {"name": "sshd"},
    "location": "/var/log/auth.log",
    "full_log": "Failed password for invalid user admin from 1.2.3.4 port 22 ssh2",
}


# ─── Normalisation ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("level", "risk"),
    [(0, "low"), (6, "low"), (7, "medium"), (9, "medium"), (10, "high"),
     (12, "high"), (13, "critical"), (15, "critical"), (None, None)],
)
def test_level_to_risk(level, risk):
    assert wazuh.level_to_risk(level) == risk


def test_normalize_sample():
    n = wazuh.normalize_wazuh_alert(SAMPLE)
    assert n.external_id == "1728123072.123456"
    assert n.rule_level == 10
    assert n.risk_level == "high"
    assert n.mitre_techniques == ["T1110"]
    assert n.agent_name == "web-01"
    assert n.source == "wazuh:web-01:sshd"
    assert n.summary.startswith("sshd: brute force")
    assert n.event_at is not None and n.event_at.year == 2026
    assert "full_log: Failed password" in n.log


def test_normalize_without_id_uses_stable_hash():
    a = {"rule": {"level": 8, "description": "x"}}
    assert wazuh.normalize_wazuh_alert(a).external_id == (
        wazuh.normalize_wazuh_alert(dict(a)).external_id
    )
    assert wazuh.normalize_wazuh_alert(a).external_id.startswith("sha256:")


def test_normalize_filters_bad_mitre_ids_and_truncates():
    a = {"id": "1", "rule": {"level": 7, "mitre": {"id": ["t1059.001", "bogus"]}},
         "full_log": "A" * 50_000}
    n = wazuh.normalize_wazuh_alert(a)
    assert n.mitre_techniques == ["T1059.001"]
    assert len(n.log) <= wazuh.MAX_LOG_CHARS


def test_normalize_rejects_non_object():
    with pytest.raises(ValueError):
        wazuh.normalize_wazuh_alert(["not", "a", "dict"])  # type: ignore[arg-type]


def test_indexer_query_shape():
    q = wazuh.build_indexer_query("2026-10-05T00:00:00+00:00", 7, 50)
    filters = q["query"]["bool"]["filter"]
    assert q["size"] == 50
    assert {"range": {"rule.level": {"gte": 7}}} in filters
    assert filters[0]["range"]["timestamp"]["gte"].startswith("2026-10-05")


# ─── Webhook ────────────────────────────────────────────────────────────

TOKEN = "t" * 40
URL = "/api/integrations/wazuh/webhook"


@pytest.fixture
def client(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "wazuh_webhook_token", TOKEN)
    ratelimit.reset()

    captured: dict = {}

    def fake_ingest(_db, alerts, **_kw):
        captured["alerts"] = alerts
        r = wazuh.IngestResult(received=len(alerts), created=len(alerts))
        return r

    monkeypatch.setattr(integ_router, "ingest_alerts", fake_ingest)
    monkeypatch.setattr(integ_router, "mark_push_received", lambda _db: None)
    app.dependency_overrides[get_db] = lambda: None
    c = TestClient(app)
    c.captured = captured  # type: ignore[attr-defined]
    yield c
    app.dependency_overrides.pop(get_db, None)


def test_webhook_disabled_without_token(monkeypatch):
    monkeypatch.setattr(get_settings(), "wazuh_webhook_token", "")
    ratelimit.reset()
    r = TestClient(app).post(URL, json=SAMPLE)
    assert r.status_code == 503


def test_webhook_rejects_missing_or_bad_token(client):
    assert client.post(URL, json=SAMPLE).status_code == 401
    r = client.post(URL, json=SAMPLE, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


@pytest.mark.parametrize(
    "payload", [SAMPLE, [SAMPLE, SAMPLE], {"alerts": [SAMPLE]}]
)
def test_webhook_accepts_supported_shapes(client, payload):
    r = client.post(URL, json=payload, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 202, r.text
    assert r.json()["received"] == len(client.captured["alerts"])


def test_webhook_rejects_non_json(client):
    r = client.post(
        URL,
        content=b"not json",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_webhook_rejects_oversized_batch(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "wazuh_webhook_max_batch", 2)
    r = client.post(
        URL, json=[SAMPLE] * 3, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert r.status_code == 413


# ─── Visibility rules ───────────────────────────────────────────────────


def _u(uid, role=UserRole.ANALYST):
    return User(id=uid, email=f"{uid}@x.com", hashed_password="x", role=role)


def test_visibility_rules():
    analyst, other, admin = _u(1), _u(2), _u(3, UserRole.ADMIN)
    own = Alert(id=1, log="x", origin="manual", user_id=1)
    foreign = Alert(id=2, log="x", origin="manual", user_id=2)
    siem = Alert(id=3, log="x", origin="wazuh", user_id=None)
    siem_claimed = Alert(id=4, log="x", origin="wazuh", user_id=2)

    assert can_view_alert(analyst, own)
    assert not can_view_alert(analyst, foreign)
    assert can_view_alert(analyst, siem)
    assert can_view_alert(analyst, siem_claimed)
    assert can_view_alert(other, foreign)
    assert all(can_view_alert(admin, a) for a in (own, foreign, siem, siem_claimed))
