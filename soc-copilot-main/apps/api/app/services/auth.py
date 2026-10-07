"""Auth primitives: password hashing + stateless JWT tokens.

JWT is signed with HS256 using `settings.jwt_secret`. Cookie storage is
managed by the router (httpOnly + SameSite=Lax). Tokens carry minimal
claims: subject (user id), role, exp.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from passlib.context import CryptContext

from app.config import get_settings

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def generate_verification_token() -> str:
    """URL-safe random token for email verification links. 43 chars (32B)."""
    return secrets.token_urlsafe(32)


def is_locked(locked_until: datetime | None) -> bool:
    if locked_until is None:
        return False
    return locked_until > datetime.now(UTC)


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_ctx.verify(plain, hashed)
    except ValueError:
        return False


def issue_token(
    *, user_id: int, role: str, password_version: int, mfa: bool = False
) -> tuple[str, datetime]:
    """Session token. ``mfa`` = the second factor was verified (Práctica 2).

    When ``MFA_REQUIRED`` is on, ``get_current_user`` rejects session tokens
    without ``mfa: true`` — so tokens issued before MFA existed stop
    working and every user is forced through enrolment.
    """
    s = get_settings()
    now = datetime.now(UTC)
    exp = now + timedelta(seconds=s.jwt_ttl_seconds)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "pv": password_version,
        "mfa": mfa,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_alg)
    return token, exp


MFA_PENDING_PURPOSE = "mfa_pending"


def issue_mfa_pending_token(*, user_id: int, password_version: int) -> tuple[str, datetime]:
    """Short-lived token proving "password OK, TOTP still missing".

    Carries ``purpose`` so it can NEVER be accepted as a session token.
    """
    s = get_settings()
    now = datetime.now(UTC)
    exp = now + timedelta(seconds=s.mfa_pending_ttl_seconds)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "pv": password_version,
        "purpose": MFA_PENDING_PURPOSE,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_alg), exp


class TokenError(Exception):
    pass


def decode_token(token: str) -> dict[str, Any]:
    s = get_settings()
    try:
        return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_alg])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid token") from exc
