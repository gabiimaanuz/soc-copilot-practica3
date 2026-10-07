"""FastAPI auth dependencies.

`get_current_user` reads the JWT from the httpOnly cookie set at login,
loads the user from the DB, and returns it. `require_admin` builds on top
to gate admin-only routes.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.config import get_settings
from app.db import DbSession
from app.models import User, UserRole
from app.services.auth import TokenError, decode_token


def _extract_token(request: Request) -> str | None:
    s = get_settings()
    cookie = request.cookies.get(s.cookie_name)
    if cookie:
        return cookie
    # Fallback: Authorization: Bearer <token> for API clients/tests.
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return None


def get_current_user(request: Request, db: DbSession) -> User:
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(token)
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
        ) from None
    # Purpose-bound tokens (e.g. "mfa_pending") are never sessions.
    if payload.get("purpose"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired token"
        )
    # Práctica 2 · MFA obligatorio: sessions must carry a verified 2nd factor.
    if get_settings().mfa_required and payload.get("mfa") is not True:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="mfa required, please log in again",
        )
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="malformed token"
        ) from None
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found"
        )
    # Reject tokens issued before the user's last password change.
    token_pv = payload.get("pv", 0)
    if token_pv != user.password_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="session invalidated, please log in again",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin role required"
        )
    return user


AdminUser = Annotated[User, Depends(require_admin)]
