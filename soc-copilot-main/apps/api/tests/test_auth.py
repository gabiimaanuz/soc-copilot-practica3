"""Auth-only tests: pure-function paths (hash, verify, JWT) plus HTTP
gating that returns 401 without DB access.
"""

from datetime import datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.auth import (
    TokenError,
    decode_token,
    hash_password,
    issue_token,
    verify_password,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ─── Password hashing ───────────────────────────────────────────────────────


def test_hash_round_trip():
    h = hash_password("secret-password-1234")
    assert h != "secret-password-1234"  # actually hashed
    assert verify_password("secret-password-1234", h)
    assert not verify_password("wrong", h)


def test_hash_is_unique_per_call():
    a = hash_password("samepass")
    b = hash_password("samepass")
    # bcrypt salts → distinct hashes for the same password
    assert a != b
    assert verify_password("samepass", a)
    assert verify_password("samepass", b)


def test_verify_returns_false_on_garbage():
    assert not verify_password("anything", "not-a-real-hash")
    assert not verify_password("", "")


# ─── JWT issue / decode ─────────────────────────────────────────────────────


def test_issue_token_round_trip():
    token, exp = issue_token(user_id=42, role="admin", password_version=0)
    assert isinstance(token, str)
    assert exp > datetime.now(exp.tzinfo)
    payload = decode_token(token)
    assert payload["sub"] == "42"
    assert payload["role"] == "admin"
    assert payload["pv"] == 0
    assert "exp" in payload and "iat" in payload


def test_decode_rejects_tampered_signature():
    token, _ = issue_token(user_id=1, role="analyst", password_version=0)
    parts = token.split(".")
    parts[2] = "tampered"
    bad = ".".join(parts)
    with pytest.raises(TokenError):
        decode_token(bad)


def test_decode_rejects_expired_token(monkeypatch):
    s = get_settings()
    expired = jwt.encode(
        {
            "sub": "1",
            "role": "analyst",
            "iat": int((datetime.now() - timedelta(hours=2)).timestamp()),
            "exp": int((datetime.now() - timedelta(hours=1)).timestamp()),
        },
        s.jwt_secret,
        algorithm=s.jwt_alg,
    )
    with pytest.raises(TokenError):
        decode_token(expired)


def test_decode_rejects_wrong_secret(monkeypatch):
    s = get_settings()
    foreign = jwt.encode(
        {"sub": "1", "role": "analyst", "exp": 9999999999},
        "different-secret-entirely",
        algorithm=s.jwt_alg,
    )
    with pytest.raises(TokenError):
        decode_token(foreign)


# ─── HTTP gates: protected endpoints reject without auth ────────────────────


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/api/explain", {"log": "ok"}),
        ("POST", "/api/recommend", {"log": "ok"}),
        ("POST", "/api/chat", {"messages": [{"role": "user", "content": "hi"}]}),
        ("GET", "/api/alerts", None),
        ("GET", "/api/alerts/1", None),
        ("GET", "/api/auth/me", None),
    ],
)
def test_protected_endpoints_return_401_without_token(method, path, body):
    if method == "POST":
        r = client.post(path, json=body)
    else:
        r = client.get(path)
    assert r.status_code == 401, (path, r.text)
    assert "AIza" not in r.text  # never leak


def test_protected_endpoints_reject_garbage_bearer():
    r = client.get(
        "/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert r.status_code == 401


def test_protected_endpoints_reject_expired_bearer():
    s = get_settings()
    expired = jwt.encode(
        {
            "sub": "1",
            "role": "analyst",
            "iat": int((datetime.now() - timedelta(hours=2)).timestamp()),
            "exp": int((datetime.now() - timedelta(hours=1)).timestamp()),
        },
        s.jwt_secret,
        algorithm=s.jwt_alg,
    )
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


# ─── Public endpoints stay open ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    ["/api/health", "/", "/docs", "/openapi.json"],
)
def test_public_endpoints_dont_require_auth(path):
    r = client.get(path)
    assert r.status_code == 200, (path, r.text)


def test_llm_models_now_requires_auth():
    # /api/llm/models used to be public. It leaks the model allowlist, so
    # it's gated behind auth in Phase 5+.
    r = client.get("/api/llm/models")
    assert r.status_code == 401
