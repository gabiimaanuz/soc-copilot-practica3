"""Práctica 2 · MFA TOTP — offline tests (no Postgres)."""
from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import mfa
from app.services.auth import decode_token, issue_mfa_pending_token, issue_token

RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


@pytest.mark.parametrize(
    ("t", "expected"),
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ],
)
def test_rfc6238_sha1_vectors(t, expected):
    assert mfa.hotp(RFC_SECRET, t // 30, digits=8) == expected


def test_verify_window_and_replay():
    now = 1_000_000.0
    code = mfa.totp(RFC_SECRET, now)
    step = mfa.verify_totp(RFC_SECRET, code, now=now)
    assert step == mfa.current_step(now)
    # Same code again → replay rejected.
    assert mfa.verify_totp(RFC_SECRET, code, last_used_step=step, now=now) is None
    # Previous step accepted (clock drift), two steps back rejected.
    prev = mfa.hotp(RFC_SECRET, mfa.current_step(now) - 1)
    assert mfa.verify_totp(RFC_SECRET, prev, now=now) is not None
    old = mfa.hotp(RFC_SECRET, mfa.current_step(now) - 2)
    assert mfa.verify_totp(RFC_SECRET, old, now=now) is None
    assert mfa.verify_totp(RFC_SECRET, "12a456", now=now) is None
    assert mfa.verify_totp(RFC_SECRET, "", now=now) is None


def test_secret_is_160_bits_base32():
    s = mfa.generate_secret()
    assert len(s) == 32 and s.isalnum() and s.upper() == s


def test_recovery_codes_single_use_and_normalised():
    codes = mfa.generate_recovery_codes()
    assert len(codes) == 10 and len(set(codes)) == 10
    hashes = [mfa.hash_recovery_code(c) for c in codes]
    remaining = mfa.consume_recovery_code(hashes, codes[0].upper().replace("-", " "))
    assert remaining is not None and len(remaining) == 9
    assert mfa.consume_recovery_code(remaining, codes[0]) is None
    assert mfa.consume_recovery_code(None, codes[1]) is None


def test_provisioning_uri_and_qr():
    uri = mfa.provisioning_uri(RFC_SECRET, "ana@example.com", "SOC Copilot")
    assert uri.startswith("otpauth://totp/SOC%20Copilot:ana%40example.com?")
    assert f"secret={RFC_SECRET}" in uri and "issuer=SOC%20Copilot" in uri
    svg = mfa.qr_svg(uri)
    assert svg.startswith("<svg") and "<path" in svg
    assert mfa.qr_data_uri(uri).startswith("data:image/svg+xml;base64,")


# ─── Session gating ─────────────────────────────────────────────────────

client = TestClient(app)


@pytest.fixture
def mfa_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "mfa_required", True)


def test_pending_token_is_never_a_session(mfa_on):
    token, _ = issue_mfa_pending_token(user_id=1, password_version=0)
    assert decode_token(token)["purpose"] == "mfa_pending"
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_session_without_mfa_claim_rejected_when_required(mfa_on):
    token, _ = issue_token(user_id=1, role="admin", password_version=0)
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert "mfa" in r.text


def test_mfa_endpoints_need_pending_cookie():
    from app.middleware import ratelimit

    ratelimit.reset()
    assert client.post("/api/auth/mfa/setup").status_code == 401
    assert client.post("/api/auth/mfa/verify", json={"code": "123456"}).status_code == 401


def test_production_refuses_mfa_disabled(monkeypatch):
    from app.config import Settings

    s = Settings(
        app_env="production",
        jwt_secret="x" * 40,
        postgres_password="strong-pw-123",
        app_encryption_key="m24ERtIpLGYhHLZ_TeXqXnXRUZ9GlMM_hwdPTSCDPQM=",
        gemini_api_key="k",
        api_cors_origins="https://soc.example.com",
        mfa_required=False,
    )
    with pytest.raises(RuntimeError, match="MFA_REQUIRED"):
        s.validate_for_runtime()
