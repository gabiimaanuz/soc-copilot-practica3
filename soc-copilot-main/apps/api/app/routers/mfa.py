"""MFA / TOTP endpoints (Práctica 2 — mejora 8.2, obligatoria para todos).

Login flow
----------
1. ``POST /api/auth/login`` (email + password) → ``mfa_required: true`` and
   an httpOnly ``soc_mfa_pending`` cookie (5 min, path ``/api/auth/mfa``).
2a. Not enrolled → ``POST /api/auth/mfa/setup`` returns the QR + secret,
    then ``POST /api/auth/mfa/verify {code}`` activates MFA, returns the
    recovery codes (shown once) and opens the session.
2b. Enrolled → ``POST /api/auth/mfa/verify {code | recovery_code}`` opens
    the session.

Wrong codes count towards the same lockout as wrong passwords
(``AUTH_LOCKOUT_THRESHOLD`` / ``AUTH_LOCKOUT_MINUTES``).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.config import get_settings
from app.db import DbSession
from app.middleware.auth import CurrentUser
from app.middleware.origin import enforce_same_origin
from app.middleware.ratelimit import auth_rate_limit
from app.models import User
from app.routers.auth import _set_session_cookie
from app.schemas.auth import (
    MfaCodeRequest,
    MfaRecoveryCodesResponse,
    MfaSetupResponse,
    MfaStatusResponse,
    MfaVerifyRequest,
    MfaVerifyResponse,
    UserMe,
)
from app.services import mfa
from app.services.audit import log_audit
from app.services.auth import (
    MFA_PENDING_PURPOSE,
    TokenError,
    decode_token,
    is_locked,
    issue_token,
)
from app.services.secrets import DecryptionError, EncryptionDisabled, decrypt, encrypt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/mfa", tags=["auth-mfa"])

_PENDING_PATH = "/api/auth/mfa"


def get_pending_user(request: Request, db: DbSession) -> User:
    """Resolve the user from the ``mfa_pending`` cookie (password already OK)."""
    s = get_settings()
    token = request.cookies.get(s.mfa_pending_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="mfa session expired, log in again")
    try:
        payload = decode_token(token)
    except TokenError:
        raise HTTPException(
            status_code=401, detail="mfa session expired, log in again"
        ) from None
    if payload.get("purpose") != MFA_PENDING_PURPOSE:
        raise HTTPException(status_code=401, detail="invalid mfa token")
    try:
        user = db.get(User, int(payload["sub"]))
    except (KeyError, TypeError, ValueError):
        user = None
    if user is None or payload.get("pv") != user.password_version:
        raise HTTPException(status_code=401, detail="mfa session expired, log in again")
    return user


def _secret(user: User) -> str:
    if not user.mfa_secret_ciphertext:
        raise HTTPException(status_code=400, detail="mfa not set up")
    try:
        return decrypt(user.mfa_secret_ciphertext)
    except (DecryptionError, EncryptionDisabled):
        logger.error("mfa.secret_unreadable", extra={"user_id": user.id})
        raise HTTPException(
            status_code=503,
            detail="MFA secret unreadable (APP_ENCRYPTION_KEY changed?) — ask an admin "
            "to reset your MFA",
        ) from None


def _register_failure(db, user: User, request: Request, reason: str) -> None:
    s = get_settings()
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    details: dict = {"reason": reason, "attempts": user.failed_login_attempts}
    if user.failed_login_attempts >= s.auth_lockout_threshold:
        user.locked_until = datetime.now(UTC) + timedelta(minutes=s.auth_lockout_minutes)
        details["locked_until"] = user.locked_until.isoformat()
    log_audit(
        db,
        actor=user,
        action="auth.mfa_failed",
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        details=details,
        request=request,
    )
    db.commit()


@router.post(
    "/setup",
    response_model=MfaSetupResponse,
    dependencies=[Depends(enforce_same_origin), Depends(auth_rate_limit)],
)
def mfa_setup(request: Request, db: DbSession) -> MfaSetupResponse:
    user = get_pending_user(request, db)
    if user.mfa_enabled:
        raise HTTPException(
            status_code=409, detail="mfa already enabled — ask an admin to reset it"
        )
    s = get_settings()
    secret = mfa.generate_secret()
    try:
        user.mfa_secret_ciphertext = encrypt(secret)
    except EncryptionDisabled:
        raise HTTPException(
            status_code=503,
            detail="APP_ENCRYPTION_KEY is not configured; MFA secrets cannot be stored",
        ) from None
    user.mfa_last_used_step = None
    log_audit(
        db,
        actor=user,
        action="auth.mfa_setup_started",
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        request=request,
    )
    db.commit()
    uri = mfa.provisioning_uri(secret, user.email, s.mfa_issuer)
    return MfaSetupResponse(
        secret=secret,
        otpauth_uri=uri,
        qr_svg_data_uri=mfa.qr_data_uri(uri),
        issuer=s.mfa_issuer,
        account=user.email,
    )


@router.post(
    "/verify",
    response_model=MfaVerifyResponse,
    dependencies=[Depends(enforce_same_origin), Depends(auth_rate_limit)],
)
def mfa_verify(
    payload: MfaVerifyRequest, request: Request, response: Response, db: DbSession
) -> MfaVerifyResponse:
    s = get_settings()
    user = get_pending_user(request, db)

    if is_locked(user.locked_until):
        raise HTTPException(status_code=401, detail="invalid code")
    if not payload.code and not payload.recovery_code:
        raise HTTPException(status_code=422, detail="code or recovery_code required")

    new_codes: list[str] | None = None
    method = "totp"

    if payload.recovery_code:
        if not user.mfa_enabled:
            raise HTTPException(status_code=400, detail="mfa not enabled yet")
        remaining = mfa.consume_recovery_code(user.mfa_recovery_codes, payload.recovery_code)
        if remaining is None:
            _register_failure(db, user, request, "bad_recovery_code")
            raise HTTPException(status_code=401, detail="invalid code")
        user.mfa_recovery_codes = remaining
        method = "recovery_code"
    else:
        step = mfa.verify_totp(
            _secret(user), payload.code or "", last_used_step=user.mfa_last_used_step
        )
        if step is None:
            _register_failure(db, user, request, "bad_totp")
            raise HTTPException(status_code=401, detail="invalid code")
        user.mfa_last_used_step = step
        if not user.mfa_enabled:
            # Enrolment completes with the first valid code.
            user.mfa_enabled = True
            user.mfa_enabled_at = datetime.now(UTC)
            new_codes = mfa.generate_recovery_codes()
            user.mfa_recovery_codes = [mfa.hash_recovery_code(c) for c in new_codes]
            method = "enrolment"

    user.failed_login_attempts = 0
    user.locked_until = None
    token, exp = issue_token(
        user_id=user.id,
        role=user.role.value,
        password_version=user.password_version,
        mfa=True,
    )
    _set_session_cookie(response, token)
    response.delete_cookie(key=s.mfa_pending_cookie_name, path=_PENDING_PATH)
    log_audit(
        db,
        actor=user,
        action="auth.mfa_enabled" if method == "enrolment" else "auth.login",
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        details={
            "success": True,
            "mfa_method": method,
            "recovery_codes_left": len(user.mfa_recovery_codes or []),
        },
        request=request,
    )
    db.commit()
    db.refresh(user)
    return MfaVerifyResponse(
        user=UserMe.model_validate(user),
        expires_at=exp,
        recovery_codes=new_codes,
        recovery_codes_left=len(user.mfa_recovery_codes or []),
    )


@router.get("/status", response_model=MfaStatusResponse)
def mfa_status(user: CurrentUser) -> MfaStatusResponse:
    return MfaStatusResponse(
        required=get_settings().mfa_required,
        enabled=user.mfa_enabled,
        enabled_at=user.mfa_enabled_at,
        recovery_codes_left=len(user.mfa_recovery_codes or []),
    )


@router.post(
    "/recovery-codes",
    response_model=MfaRecoveryCodesResponse,
    dependencies=[Depends(enforce_same_origin), Depends(auth_rate_limit)],
)
def regenerate_recovery_codes(
    payload: MfaCodeRequest, user: CurrentUser, request: Request, db: DbSession
) -> MfaRecoveryCodesResponse:
    """New set of recovery codes (invalidates the old ones). Needs a TOTP."""
    if not user.mfa_enabled:
        raise HTTPException(status_code=400, detail="mfa not enabled")
    step = mfa.verify_totp(
        _secret(user), payload.code, last_used_step=user.mfa_last_used_step
    )
    if step is None:
        _register_failure(db, user, request, "bad_totp_regen")
        raise HTTPException(status_code=401, detail="invalid code")
    user.mfa_last_used_step = step
    codes = mfa.generate_recovery_codes()
    user.mfa_recovery_codes = [mfa.hash_recovery_code(c) for c in codes]
    log_audit(
        db,
        actor=user,
        action="auth.mfa_recovery_regenerated",
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        request=request,
    )
    db.commit()
    return MfaRecoveryCodesResponse(recovery_codes=codes)
