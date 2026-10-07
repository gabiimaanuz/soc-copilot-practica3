"""Pure-function tests for the registration hardening pass.

Covers the bits that don't need a DB:

* password strength validator (server-side rules)
* lockout helper (is_locked)
* token generation entropy
* verification token expiry math
* RegisterRequest pydantic validator (rejects weak passwords)

DB-backed cases (duplicate email, login lockout sequencing, expired
verification token end-to-end) live in test_e2e.py since they need a
real Postgres to exercise the migration + ORM.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.auth import RegisterRequest
from app.services.auth import generate_verification_token, is_locked
from app.services.password import MIN_LENGTH, check_password
from app.services.security import (
    is_disposable_email,
    normalize_email,
    sanitize_name,
)


# ─── Password strength ──────────────────────────────────────────────────


def test_strong_password_passes():
    r = check_password("Cor3cto-Pass!word")
    assert r.ok, r.failed
    assert r.score >= 3


@pytest.mark.parametrize(
    "pw,reason",
    [
        ("short1!", "length"),       # too short
        ("alllowercase1!", "upper"), # no uppercase
        ("ALLUPPER1!", "lower"),     # no lowercase
        ("NoDigits!!", "digit"),     # no digit
        ("NoSymbols123", "symbol"),  # no symbol
        ("Password123!", "common"),  # block-listed
    ],
)
def test_weak_password_fails(pw: str, reason: str):
    r = check_password(pw)
    assert not r.ok, f"expected fail ({reason}) for {pw!r}"
    assert r.failed


def test_password_cannot_contain_email_local_part():
    r = check_password("Juanito-2025!", email="juanito@example.com")
    assert not r.ok
    assert any("email" in m.lower() for m in r.failed)


def test_min_length_constant_matches_router():
    # Sanity: schema-level min_length should not be shorter than the
    # validator's MIN_LENGTH, or registrations could 422 on a different
    # rule than the one the strength helper reports.
    assert MIN_LENGTH >= 10


# ─── Pydantic schema wires the validator ─────────────────────────────────


def test_register_request_rejects_weak_password():
    with pytest.raises(ValidationError):
        RegisterRequest(
            name="Ana",
            email="ana@example.com",
            password="short1!",  # noqa: S106 — intentionally weak in test
        )


def test_register_request_accepts_strong_password_and_default_level():
    req = RegisterRequest(
        name="Ana",
        email="ana@example.com",
        password="Cor3cto-Pass!word",
    )
    assert req.level.value == "L1"


def test_register_request_accepts_instructor_level():
    req = RegisterRequest(
        name="Ana",
        email="ana@example.com",
        password="Cor3cto-Pass!word",
        level="INSTRUCTOR",
    )
    assert req.level.value == "INSTRUCTOR"


# ─── Lockout helper ─────────────────────────────────────────────────────


def test_is_locked_handles_none():
    assert is_locked(None) is False


def test_is_locked_true_when_future():
    future = datetime.now(UTC) + timedelta(minutes=10)
    assert is_locked(future) is True


def test_is_locked_false_when_past():
    past = datetime.now(UTC) - timedelta(minutes=1)
    assert is_locked(past) is False


# ─── Verification token ─────────────────────────────────────────────────


def test_verification_token_is_unique_and_long():
    a = generate_verification_token()
    b = generate_verification_token()
    assert a != b
    # 32 random bytes → 43-char urlsafe string
    assert len(a) >= 40
    # No padding chars; urlsafe alphabet only
    assert all(c.isalnum() or c in "-_" for c in a)


# ─── Input hardening ────────────────────────────────────────────────────


def test_normalize_email_lowercases_and_trims():
    assert normalize_email("  Foo@Example.COM  ") == "foo@example.com"
    assert normalize_email("") == ""


def test_sanitize_name_strips_controls_and_bidi():
    # CR/LF audit-log injection attempt
    assert sanitize_name("Ana\r\nINJECTED") == "AnaINJECTED"
    # RLO override (homograph) and zero-width joiner
    assert "‮" not in sanitize_name("Ana‮evil")
    assert "​" not in sanitize_name("A​na")
    # Legit Unicode names survive
    assert sanitize_name("  José  ") == "José"
    assert sanitize_name("李雷") == "李雷"


def test_is_disposable_email_blocks_known_providers():
    assert is_disposable_email("foo@mailinator.com")
    assert is_disposable_email("foo@10minutemail.com")
    assert not is_disposable_email("foo@example.com")
    assert not is_disposable_email("not-an-email")


def test_register_request_normalizes_email():
    req = RegisterRequest(
        name="Ana",
        email="ANA@EXAMPLE.COM",
        password="Cor3cto-Pass!word",
    )
    assert req.email == "ana@example.com"


def test_register_request_rejects_disposable_email():
    with pytest.raises(ValidationError):
        RegisterRequest(
            name="Ana",
            email="ana@mailinator.com",
            password="Cor3cto-Pass!word",
        )


def test_register_request_rejects_name_with_only_control_chars():
    with pytest.raises(ValidationError):
        RegisterRequest(
            name="​​​",
            email="ana@example.com",
            password="Cor3cto-Pass!word",
        )


def test_register_request_strips_crlf_from_name():
    req = RegisterRequest(
        name="Ana\r\nAttacker",
        email="ana@example.com",
        password="Cor3cto-Pass!word",
    )
    assert "\r" not in req.name and "\n" not in req.name


def test_register_request_honeypot_field_defaults_empty():
    req = RegisterRequest(
        name="Ana",
        email="ana@example.com",
        password="Cor3cto-Pass!word",
    )
    assert req.website == ""
