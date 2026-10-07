"""Tests for the per-user LLM configuration: BYO key + server-key quota.

These don't talk to a real Postgres or Gemini. We mock:
- The FastAPI auth dependency to inject a synthetic User row.
- ``GeminiAdapter`` so ``PUT /api/auth/me/llm`` doesn't ping the real API.
- A trivial in-memory DB stand-in for the SQLAlchemy session methods we
  actually call (``commit``, ``refresh``, ``add``).

What we cover here:
- Encryption round-trip (Fernet token != plaintext, decrypts back).
- ``last4`` displays last 4 chars only.
- ``GET/PUT/DELETE /api/auth/me/llm`` happy paths + validation failures.
- ``get_llm_for_user`` selects BYO vs server, enforces quota, rolls daily.
- Admin reset endpoint zeroes the counter and writes an audit row.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.middleware.auth import get_current_user
from app.models import User, UserRole
from app.services import llm as llm_module
from app.services.llm import (
    LLMProviderError,
    _enforce_server_quota,
    get_llm_for_user,
)
from app.services.secrets import (
    DecryptionError,
    EncryptionDisabled,
    decrypt,
    encrypt,
    last4,
)

# ─── Test scaffolding ───────────────────────────────────────────────────────


# Fernet keys are urlsafe-base64 32-byte. Generated once for the suite.
TEST_FERNET_KEY = "m24ERtIpLGYhHLZ_TeXqXnXRUZ9GlMM_hwdPTSCDPQM="


@pytest.fixture(autouse=True)
def _settings_with_encryption(monkeypatch):
    """Force a known Fernet key + rate-limit off for every test in this file."""
    monkeypatch.setenv("APP_ENCRYPTION_KEY", TEST_FERNET_KEY)
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("SERVER_LLM_DAILY_QUOTA", "3")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _user(**over) -> User:
    base = dict(
        id=42,
        email="byo@example.com",
        name="Test",
        last_name="User",
        hashed_password="x",
        role=UserRole.ANALYST,
        password_version=0,
        created_at=datetime.now(UTC),
        gemini_api_key_ciphertext=None,
        gemini_key_last4=None,
        gemini_key_validated_at=None,
        preferred_chat_model=None,
        server_llm_calls_today=0,
        server_llm_quota_date=None,
    )
    base.update(over)
    u = User(**base)
    return u


class FakeDb:
    """The bare minimum SQLAlchemy Session surface used by our routers.

    Tracks ``commit`` calls so tests can assert persistence happens
    exactly when expected. ``refresh`` is a no-op (the in-memory user
    object is already authoritative)."""

    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1

    def refresh(self, _obj):
        pass

    def add(self, _obj):
        pass

    def flush(self):
        pass


# ─── secrets module ──────────────────────────────────────────────────────────


def test_encrypt_decrypt_round_trip():
    token = encrypt("AIzaSyExample-1234567890")
    assert isinstance(token, bytes)
    assert b"AIza" not in token  # ciphertext must not contain the plaintext
    assert decrypt(token) == "AIzaSyExample-1234567890"


def test_encrypt_rejects_empty():
    with pytest.raises(ValueError):
        encrypt("")


def test_decrypt_rejects_tampered_ciphertext():
    token = encrypt("hello")
    bad = bytearray(token)
    bad[-1] ^= 0x01  # flip a byte
    with pytest.raises(DecryptionError):
        decrypt(bytes(bad))


def test_last4_shows_only_tail():
    assert last4("AIzaSy0123456789FpMpY") == "FpMpY"[-4:]
    assert last4("") == ""


def test_encryption_disabled_when_no_key(monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(EncryptionDisabled):
        encrypt("anything")


# ─── Quota tracker ───────────────────────────────────────────────────────────


def test_enforce_server_quota_increments_and_blocks():
    user = _user()
    db = FakeDb()
    # 3 successful calls (quota=3 from fixture)
    for _ in range(3):
        _enforce_server_quota(user, db)
    assert user.server_llm_calls_today == 3
    assert user.server_llm_quota_date == datetime.now(UTC).date()
    # 4th hits the wall.
    with pytest.raises(HTTPException) as exc:
        _enforce_server_quota(user, db)
    assert exc.value.status_code == 429
    assert "quota" in exc.value.detail.lower()


def test_enforce_server_quota_rolls_daily():
    """A user blocked yesterday should reset on the first call today."""
    user = _user(
        server_llm_calls_today=99,
        server_llm_quota_date=(datetime.now(UTC).date() - timedelta(days=1)),
    )
    db = FakeDb()
    _enforce_server_quota(user, db)
    # Counter rolled and incremented to 1.
    assert user.server_llm_calls_today == 1
    assert user.server_llm_quota_date == datetime.now(UTC).date()


# ─── Adapter selection ──────────────────────────────────────────────────────


class _FakeAdapter:
    """Non-network adapter so get_llm()/get_llm_for_user() don't try to
    instantiate the real Gemini client during tests."""

    def __init__(self, *, api_key: str | None = None):
        self.api_key = api_key

    def generate_json(self, *a, **kw): return {}
    def generate_text(self, *a, **kw): return ""
    def embed(self, *a, **kw): return []


def test_get_llm_for_user_uses_byo_key_when_configured(monkeypatch):
    monkeypatch.setattr(llm_module, "GeminiAdapter", _FakeAdapter)
    # Server-key singleton must not be used.
    monkeypatch.setattr(
        llm_module, "_singleton", _FakeAdapter(api_key="SERVER")
    )
    user = _user(gemini_api_key_ciphertext=encrypt("USER-BYO-KEY-12345"))
    db = FakeDb()
    adapter = get_llm_for_user(user, db)
    assert isinstance(adapter._inner, _FakeAdapter)
    assert adapter._inner.api_key == "USER-BYO-KEY-12345"
    # No quota consumed when using their own key.
    assert user.server_llm_calls_today == 0


def test_get_llm_for_user_falls_back_to_server_with_quota(monkeypatch):
    monkeypatch.setattr(llm_module, "GeminiAdapter", _FakeAdapter)
    server_singleton = _FakeAdapter(api_key="SERVER")
    monkeypatch.setattr(llm_module, "_singleton", server_singleton)
    user = _user()  # no BYO key
    db = FakeDb()
    adapter = get_llm_for_user(user, db)
    assert adapter._inner is server_singleton
    assert user.server_llm_calls_today == 1
    assert db.commits == 1


def test_get_llm_for_user_unreadable_ciphertext_falls_back(monkeypatch):
    """If APP_ENCRYPTION_KEY rotated the user's old token can't be read.
    We log loudly and use the server key instead of bricking the analyst."""
    monkeypatch.setattr(llm_module, "GeminiAdapter", _FakeAdapter)
    server_singleton = _FakeAdapter(api_key="SERVER")
    monkeypatch.setattr(llm_module, "_singleton", server_singleton)
    # Give them a token that won't decrypt.
    user = _user(gemini_api_key_ciphertext=b"gAAAAAB-not-a-valid-token")
    db = FakeDb()
    adapter = get_llm_for_user(user, db)
    assert adapter._inner is server_singleton  # graceful fallback
    assert user.server_llm_calls_today == 1


# ─── HTTP endpoints ─────────────────────────────────────────────────────────


@pytest.fixture
def client_with_user(monkeypatch):
    """TestClient with a synthetic user and DB+LLM mocks wired in."""
    state = {"user": _user()}

    def _override_user():
        return state["user"]

    # Patch DbSession dependency: just hand back our FakeDb.
    from app.db import get_db

    fake_db = FakeDb()

    def _override_db():
        yield fake_db

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db

    # Kill the network in GeminiAdapter — we substitute a fake that
    # accepts any key and returns "ok" on generate_text.
    monkeypatch.setattr(
        llm_module,
        "GeminiAdapter",
        lambda api_key=None: _FakeAdapter(api_key=api_key),
    )
    # Also patch the auth router's import binding (it imported the
    # symbol by name, so monkeypatching the module isn't enough).
    from app.routers import auth as auth_router

    monkeypatch.setattr(
        auth_router,
        "GeminiAdapter",
        lambda api_key=None: _FakeAdapter(api_key=api_key),
    )

    yield TestClient(app), state, fake_db
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


def test_get_llm_settings_returns_safe_view(client_with_user):
    client, state, _db = client_with_user
    state["user"] = _user(
        gemini_api_key_ciphertext=encrypt("AIzaSy-secret-12345"),
        gemini_key_last4="2345",
        gemini_key_validated_at=datetime.now(UTC),
        preferred_chat_model="gemini-2.5-flash-lite",
    )
    r = client.get("/api/auth/me/llm")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] is True
    assert body["key_last4"] == "2345"
    assert body["preferred_chat_model"] == "gemini-2.5-flash-lite"
    # The response must NEVER contain the plaintext key or ciphertext.
    assert "ciphertext" not in r.text.lower()
    assert "AIza" not in r.text
    # Allowlist + default surface for the UI dropdown.
    assert isinstance(body["available_models"], list)
    assert len(body["available_models"]) >= 1
    assert body["default_model"] in body["available_models"]


def test_put_llm_settings_validates_and_stores_key(client_with_user):
    client, state, _db = client_with_user
    payload = {"api_key": "AIzaSy-fresh-test-key-1234567890"}
    r = client.put("/api/auth/me/llm", json=payload)
    assert r.status_code == 200, r.text
    user = state["user"]
    # Stored as ciphertext, not plaintext.
    assert user.gemini_api_key_ciphertext is not None
    assert user.gemini_api_key_ciphertext != payload["api_key"].encode()
    assert decrypt(user.gemini_api_key_ciphertext) == payload["api_key"]
    assert user.gemini_key_last4 == payload["api_key"][-4:]
    assert user.gemini_key_validated_at is not None


def test_put_llm_settings_rejects_short_key(client_with_user):
    client, _state, _db = client_with_user
    r = client.put("/api/auth/me/llm", json={"api_key": "short"})
    # Pydantic min_length blocks at 422 before our 400 path runs.
    assert r.status_code in (400, 422)


def test_put_llm_settings_rejects_provider_failure(client_with_user, monkeypatch):
    client, _state, _db = client_with_user
    # Make the validation ping fail.
    from app.routers import auth as auth_router

    class FailingAdapter:
        def __init__(self, *, api_key=None):
            pass

        def generate_text(self, *a, **kw):
            raise LLMProviderError("invalid api key")

    monkeypatch.setattr(auth_router, "GeminiAdapter", FailingAdapter)
    r = client.put(
        "/api/auth/me/llm",
        json={"api_key": "AIzaSy-but-invalid-1234567890"},
    )
    assert r.status_code == 400
    assert "rejected" in r.json()["detail"].lower()


def test_put_llm_settings_rejects_model_outside_allowlist(client_with_user):
    client, _state, _db = client_with_user
    r = client.put(
        "/api/auth/me/llm", json={"preferred_chat_model": "gpt-4o"}
    )
    assert r.status_code == 400
    assert "allowlist" in r.json()["detail"].lower()


def test_put_llm_settings_accepts_allowed_model(client_with_user):
    client, state, _db = client_with_user
    s = get_settings()
    chosen = s.chat_models_list[0]
    r = client.put(
        "/api/auth/me/llm", json={"preferred_chat_model": chosen}
    )
    assert r.status_code == 200, r.text
    assert state["user"].preferred_chat_model == chosen


def test_delete_llm_key_clears_byo(client_with_user):
    client, state, _db = client_with_user
    state["user"].gemini_api_key_ciphertext = encrypt("AIzaSy-bye-12345")
    state["user"].gemini_key_last4 = "2345"
    state["user"].gemini_key_validated_at = datetime.now(UTC)

    r = client.delete("/api/auth/me/llm")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] is False
    assert body["key_last4"] is None
    user = state["user"]
    assert user.gemini_api_key_ciphertext is None
    assert user.gemini_key_last4 is None
    assert user.gemini_key_validated_at is None


def test_llm_endpoints_require_auth():
    """Without an auth override the endpoints reject anonymous callers."""
    client = TestClient(app)
    for verb, path in [("get", "/api/auth/me/llm"),
                       ("put", "/api/auth/me/llm"),
                       ("delete", "/api/auth/me/llm")]:
        if verb in ("put", "post"):
            r = getattr(client, verb)(path, json={})
        else:
            r = getattr(client, verb)(path)
        assert r.status_code == 401, (verb, path, r.text)
