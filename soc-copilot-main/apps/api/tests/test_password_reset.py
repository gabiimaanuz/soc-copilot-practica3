"""«¿Has olvidado tu contraseña?» — offline tests (no Postgres)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.middleware import ratelimit


class _EmptyDB:
    """No user matches anything."""

    def scalar(self, *_a, **_k):
        return None

    def add(self, _o):
        pass

    def flush(self):
        pass

    def commit(self):
        pass


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: _EmptyDB()
    ratelimit.reset()
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def test_forgot_unknown_email_gives_generic_202(client):
    r = client.post("/api/auth/forgot-password", json={"email": "nadie@example.com"})
    assert r.status_code == 202
    body = r.json()
    assert "Si existe una cuenta" in body["message"]
    assert body["reset_link_dev"] is None


def test_forgot_rejects_invalid_email(client):
    assert client.post("/api/auth/forgot-password", json={"email": "x"}).status_code == 422


def test_forgot_per_email_throttle(client):
    # 3 per hour per address; the 4th is throttled (IP bucket allows 5/min).
    for _ in range(3):
        assert client.post(
            "/api/auth/forgot-password", json={"email": "spam@example.com"}
        ).status_code == 202
    assert client.post(
        "/api/auth/forgot-password", json={"email": "spam@example.com"}
    ).status_code == 429


def test_reset_with_unknown_token_is_400(client):
    r = client.post(
        "/api/auth/reset-password",
        json={"token": "x" * 43, "new_password": "Nueva-Clave-Segura-2026!"},
    )
    assert r.status_code == 400


def test_reset_rejects_weak_password(client):
    r = client.post(
        "/api/auth/reset-password", json={"token": "x" * 43, "new_password": "corta"}
    )
    assert r.status_code == 422
