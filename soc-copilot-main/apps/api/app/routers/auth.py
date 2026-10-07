import hashlib
import logging
import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select

from app.config import get_settings
from app.db import DbSession
from app.middleware.auth import CurrentUser
from app.middleware.origin import enforce_same_origin
from app.middleware.ratelimit import (
    auth_rate_limit,
    check_email_rate_limit,
    forgot_password_email_rate_limit,
    register_email_rate_limit,
)
from app.models import User, UserLevel, UserRole
from app.schemas.auth import (
    CheckEmailResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LLMSettingsResponse,
    LLMSettingsUpdate,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    UpdateProfileRequest,
    UserMe,
    VerifyEmailRequest,
)
from app.services.auth import (
    generate_verification_token,
    hash_password,
    is_locked,
    issue_mfa_pending_token,
    issue_token,
    verify_password,
)
from app.services.audit import log_audit
from app.services.email import (
    password_reset_link,
    send_password_reset_email,
    send_verification_email,
)
from app.services.llm import GeminiAdapter, LLMProviderError
from app.services.secrets import EncryptionDisabled, encrypt, last4
from app.services.security import equalize_timing
from app.services.settings import is_public_registration_enabled

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _set_mfa_pending_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        key=s.mfa_pending_cookie_name,
        value=token,
        httponly=True,
        secure=s.effective_cookie_secure,
        samesite=s.effective_cookie_samesite,
        max_age=s.mfa_pending_ttl_seconds,
        path="/api/auth/mfa",
    )


def _set_session_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        key=s.cookie_name,
        value=token,
        httponly=True,
        secure=s.effective_cookie_secure,
        samesite=s.effective_cookie_samesite,
        max_age=s.jwt_ttl_seconds,
        path="/",
    )


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_same_origin), Depends(auth_rate_limit)],
)
def register(
    payload: RegisterRequest, db: DbSession, request: Request
) -> RegisterResponse:
    """Bootstrap or invitation-style registration.

    The very first user to register becomes ADMIN and is auto-verified;
    everyone after is an ANALYST with the chosen seniority level (L1 / L2 /
    INSTRUCTOR). Once at least one user exists, public registration is
    rejected unless ``ALLOW_PUBLIC_REGISTRATION=true`` — admin-only invites
    are the secure default after bootstrap.

    When ``AUTH_REQUIRE_EMAIL_VERIFICATION`` is on the new user can't log
    in until they click the verification link. Outside production we
    return that link in the response so the flow is demoable without SMTP.
    """
    started = time.monotonic()
    settings = get_settings()

    # Honeypot: a real user can never see the "website" field. If it's
    # filled, treat as a bot — return a believable 201 with a fake user
    # so scanners think they succeeded and move on, but never persist.
    if payload.website:
        logger.warning(
            "auth.register_honeypot_tripped",
            extra={"ip": request.client.host if request.client else None},
        )
        log_audit(
            db,
            actor_email=payload.email,
            action="auth.register_honeypot",
            target_type="user",
            target_label=payload.email,
            details={"honeypot_value_len": len(payload.website)},
            request=request,
        )
        db.commit()
        equalize_timing(started, min_seconds=0.3)
        fake = User(
            id=0,
            email=payload.email,
            name=payload.name,
            last_name="",
            hashed_password="",
            role=UserRole.ANALYST,
            level=UserLevel.L1,
            requested_level=payload.level,
            level_approved=False,
            is_verified=False,
            created_at=datetime.now(UTC),
        )
        return RegisterResponse(
            user=UserMe.model_validate(fake),
            verification_required=False,
            verification_link_dev=None,
        )

    # Per-email throttle on TOP of per-IP. A distributed botnet rotating
    # IPs to flood a single target inbox still gets capped here.
    register_email_rate_limit(payload.email)

    is_first = db.scalar(select(User).limit(1)) is None

    # After bootstrap, gate self-service registration behind a flag so an
    # unauthenticated attacker can't quietly create analyst accounts.
    # The flag lives in app_settings (admin-toggleable from the UI) with
    # ALLOW_PUBLIC_REGISTRATION as the env-level fallback.
    if not is_first and not is_public_registration_enabled(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="public registration is disabled",
        )

    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing:
        # Equalize timing so 409 (taken) and 201 (created) responses
        # don't differ in latency enough to enumerate via stopwatch.
        equalize_timing(started, min_seconds=0.3)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already registered"
        )

    # Seniority gate: a self-served analyst is always pinned to L1 until
    # an admin reviews the request and assigns a level. The level they
    # picked is kept in ``requested_level`` so the admin sees the
    # self-assessment as context. Bootstrap admin gets INSTRUCTOR
    # auto-approved because there's nobody else to approve them.
    if is_first:
        effective_level = UserLevel.INSTRUCTOR
        level_approved = True
    else:
        effective_level = UserLevel.L1
        level_approved = False
    requested_level = UserLevel.INSTRUCTOR if is_first else payload.level

    requires_verification = (
        settings.auth_require_email_verification and not is_first
    )
    token = generate_verification_token() if requires_verification else None
    sent_at = datetime.now(UTC) if requires_verification else None

    user = User(
        email=payload.email,
        name=payload.name,
        hashed_password=hash_password(payload.password),
        role=UserRole.ADMIN if is_first else UserRole.ANALYST,
        level=effective_level,
        requested_level=requested_level,
        level_approved=level_approved,
        is_verified=not requires_verification,
        email_verified_at=datetime.now(UTC) if not requires_verification else None,
        email_verification_token=token,
        email_verification_sent_at=sent_at,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_audit(
        db,
        actor=user,
        action="auth.register",
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        details={
            "role": user.role.value,
            "level": user.level.value,
            "is_first": is_first,
            "verification_required": requires_verification,
        },
        request=request,
    )
    db.commit()

    # Try real SMTP delivery first. If SMTP is configured the email goes
    # out and we never leak the token. If SMTP is unconfigured (or fails)
    # we fall back to the dev-only behaviour of returning the link in the
    # response, but ONLY outside production — in prod a broken SMTP must
    # be visible (admin can resend the verification from the panel).
    verification_link_dev: str | None = None
    if requires_verification and token:
        sent = send_verification_email(
            to_email=user.email, to_name=user.name or "", token=token
        )
        if not sent and not settings.is_production:
            verification_link_dev = (
                f"{settings.web_base_url.rstrip('/')}/verify?token={token}"
            )
            logger.info(
                "auth.verification_link_issued_dev",
                extra={"user_id": user.id, "link": verification_link_dev},
            )

    return RegisterResponse(
        user=UserMe.model_validate(user),
        verification_required=requires_verification,
        verification_link_dev=verification_link_dev,
    )


@router.get(
    "/check-email",
    response_model=CheckEmailResponse,
    dependencies=[Depends(check_email_rate_limit)],
)
def check_email(email: str, db: DbSession) -> CheckEmailResponse:
    """Real-time availability check for the register form.

    Hardened against email enumeration scanners:

    * Tight rate limit (10/min/IP via dependency) — a human form types
      one query per debounce, a scraper trips this in seconds.
    * Response time floored to ~150ms so DB-hit vs DB-miss can't be
      timed apart.
    """
    started = time.monotonic()
    email_norm = email.strip().lower()
    if "@" not in email_norm or len(email_norm) > 255:
        equalize_timing(started)
        return CheckEmailResponse(available=False)
    existing = db.scalar(select(User).where(User.email == email_norm))
    equalize_timing(started)
    return CheckEmailResponse(available=existing is None)


@router.post(
    "/verify-email",
    response_model=UserMe,
    dependencies=[Depends(enforce_same_origin), Depends(auth_rate_limit)],
)
def verify_email(
    payload: VerifyEmailRequest, db: DbSession, request: Request
) -> UserMe:
    """Activate an account from the verification link.

    Tokens are single-use and expire after
    ``EMAIL_VERIFICATION_TTL_HOURS``. We deliberately return the same
    error for "no such token" and "expired token" so a stolen link can't
    be probed for liveness.
    """
    settings = get_settings()
    user = db.scalar(
        select(User).where(User.email_verification_token == payload.token)
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="token inválido o expirado",
        )

    ttl = timedelta(hours=settings.email_verification_ttl_hours)
    if (
        user.email_verification_sent_at is None
        or datetime.now(UTC) > user.email_verification_sent_at + ttl
    ):
        log_audit(
            db,
            actor=user,
            action="auth.verify_failed",
            target_type="user",
            target_id=user.id,
            target_label=user.email,
            details={"reason": "expired"},
            request=request,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="token inválido o expirado",
        )

    user.is_verified = True
    user.email_verified_at = datetime.now(UTC)
    user.email_verification_token = None
    user.email_verification_sent_at = None
    db.commit()
    db.refresh(user)
    log_audit(
        db,
        actor=user,
        action="auth.email_verified",
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        request=request,
    )
    db.commit()
    return UserMe.model_validate(user)


@router.post(
    "/login",
    response_model=LoginResponse,
    dependencies=[Depends(enforce_same_origin), Depends(auth_rate_limit)],
)
def login(
    payload: LoginRequest, db: DbSession, response: Response, request: Request
) -> LoginResponse:
    settings = get_settings()
    user = db.scalar(select(User).where(User.email == payload.email))

    # Lockout check happens BEFORE password verification — we don't even
    # peek at the hash while locked, so a lock can't be partially
    # circumvented by timing.
    if user is not None and is_locked(user.locked_until):
        log_audit(
            db,
            actor=user,
            action="auth.login_blocked",
            target_type="user",
            target_id=user.id,
            target_label=user.email,
            details={"reason": "locked"},
            request=request,
        )
        db.commit()
        # Same opaque message as bad credentials — never reveal lockout
        # state, that would help an attacker map valid accounts.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        )

    if user is None:
        # Equalise timing: still hash something so existence is harder to
        # probe via response latency.
        hash_password(payload.password)
        valid_password = False
    else:
        valid_password = verify_password(payload.password, user.hashed_password)

    if not valid_password:
        details: dict = {"success": False}
        if user is not None:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            details["attempts"] = user.failed_login_attempts
            if user.failed_login_attempts >= settings.auth_lockout_threshold:
                user.locked_until = datetime.now(UTC) + timedelta(
                    minutes=settings.auth_lockout_minutes
                )
                details["locked_until"] = user.locked_until.isoformat()
                log_audit(
                    db,
                    actor=user,
                    action="auth.lockout",
                    target_type="user",
                    target_id=user.id,
                    target_label=user.email,
                    details={
                        "attempts": user.failed_login_attempts,
                        "locked_minutes": settings.auth_lockout_minutes,
                    },
                    request=request,
                )
        log_audit(
            db,
            actor_id=user.id if user else None,
            actor_email=user.email if user else payload.email,
            action="auth.login_failed",
            target_type="user",
            target_id=user.id if user else None,
            target_label=payload.email,
            details=details,
            request=request,
        )
        db.commit()
        # Don't leak which step failed.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        )

    # Verification gate — only enforced once at least one admin exists,
    # because the bootstrap user always gets auto-verified.
    if settings.auth_require_email_verification and not user.is_verified:
        log_audit(
            db,
            actor=user,
            action="auth.login_blocked",
            target_type="user",
            target_id=user.id,
            target_label=user.email,
            details={"reason": "not_verified"},
            request=request,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="email no verificado — revisa tu bandeja",
        )

    # Successful login → clear lockout state.
    user.failed_login_attempts = 0
    user.locked_until = None

    # Práctica 2 · MFA obligatorio: the password alone never opens a
    # session. Hand out a 5-minute "mfa_pending" token (httpOnly cookie
    # scoped to /api/auth/mfa) and let the UI run setup or verification.
    if settings.mfa_required:
        pending, pending_exp = issue_mfa_pending_token(
            user_id=user.id, password_version=user.password_version
        )
        _set_mfa_pending_cookie(response, pending)
        response.delete_cookie(key=settings.cookie_name, path="/")
        log_audit(
            db,
            actor=user,
            action="auth.login_password_ok",
            target_type="user",
            target_id=user.id,
            target_label=user.email,
            details={"mfa_enrolled": user.mfa_enabled},
            request=request,
        )
        db.commit()
        return LoginResponse(
            user=None,
            expires_at=pending_exp,
            mfa_required=True,
            mfa_setup_required=not user.mfa_enabled,
        )

    token, exp = issue_token(
        user_id=user.id, role=user.role.value, password_version=user.password_version
    )
    _set_session_cookie(response, token)
    log_audit(
        db,
        actor=user,
        action="auth.login",
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        details={"success": True, "level": user.level.value},
        request=request,
    )
    db.commit()
    return LoginResponse(user=UserMe.model_validate(user), expires_at=exp)


# ── «¿Has olvidado tu contraseña?» (Práctica 2) ─────────────────────────

_FORGOT_MSG = (
    "Si existe una cuenta con ese email, te hemos enviado un enlace para "
    "restablecer la contraseña. Revisa tu bandeja (y la carpeta de spam)."
)


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(enforce_same_origin), Depends(auth_rate_limit)],
)
def forgot_password(
    payload: ForgotPasswordRequest, db: DbSession, request: Request
) -> ForgotPasswordResponse:
    """Email a single-use reset link.

    Anti-enumeration: same message and similar latency whether or not the
    account exists. Only the SHA-256 of the token is stored.
    """
    started = time.monotonic()
    settings = get_settings()
    forgot_password_email_rate_limit(payload.email)

    user = db.scalar(select(User).where(User.email == payload.email))
    link_dev: str | None = None
    if user is not None:
        token = generate_verification_token()
        user.password_reset_token_hash = _hash_reset_token(token)
        user.password_reset_sent_at = datetime.now(UTC)
        log_audit(
            db,
            actor=user,
            action="auth.password_reset_requested",
            target_type="user",
            target_id=user.id,
            target_label=user.email,
            request=request,
        )
        db.commit()
        sent = send_password_reset_email(user.email, user.name or "", token)
        if not sent and not settings.is_production:
            # Same dev-only fallback as email verification.
            link_dev = password_reset_link(token)
            logger.info(
                "auth.password_reset_link_dev",
                extra={"user_id": user.id, "link": link_dev},
            )
    equalize_timing(started, min_seconds=0.4)
    return ForgotPasswordResponse(message=_FORGOT_MSG, reset_link_dev=link_dev)


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(enforce_same_origin), Depends(auth_rate_limit)],
)
def reset_password(
    payload: ResetPasswordRequest, db: DbSession, request: Request, response: Response
) -> None:
    settings = get_settings()
    user = db.scalar(
        select(User).where(
            User.password_reset_token_hash == _hash_reset_token(payload.token)
        )
    )
    expired = (
        user is None
        or user.password_reset_sent_at is None
        or datetime.now(UTC)
        > user.password_reset_sent_at + timedelta(minutes=settings.password_reset_ttl_minutes)
    )
    if expired:
        if user is not None:
            user.password_reset_token_hash = None
            user.password_reset_sent_at = None
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="enlace inválido o caducado — solicita uno nuevo",
        )

    user.hashed_password = hash_password(payload.new_password)
    # Invalidates every open session (JWT `pv` claim).
    user.password_version = (user.password_version or 0) + 1
    user.password_reset_token_hash = None
    user.password_reset_sent_at = None
    user.failed_login_attempts = 0
    user.locked_until = None
    # Clicking the emailed link proves ownership of the address.
    if not user.is_verified:
        user.is_verified = True
        user.email_verified_at = datetime.now(UTC)
        user.email_verification_token = None
    log_audit(
        db,
        actor=user,
        action="auth.password_reset",
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        request=request,
    )
    db.commit()
    response.delete_cookie(key=settings.cookie_name, path="/")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: DbSession) -> None:
    s = get_settings()
    response.delete_cookie(key=s.cookie_name, path="/")
    response.delete_cookie(key=s.mfa_pending_cookie_name, path="/api/auth/mfa")
    # Best-effort identify the user for the audit trail; logout never fails
    # auth even if the cookie is missing or stale.
    user_id: int | None = None
    user_email: str = "system"
    cookie = request.cookies.get(s.cookie_name)
    if cookie:
        try:
            from app.services.auth import decode_token

            payload = decode_token(cookie)
            user_id = int(payload.get("sub")) if payload.get("sub") else None
            if user_id:
                user = db.scalar(select(User).where(User.id == user_id))
                if user:
                    user_email = user.email
        except Exception:
            user_id = None

    log_audit(
        db,
        actor_id=user_id,
        actor_email=user_email,
        action="auth.logout",
        request=request,
    )
    db.commit()


@router.get("/me", response_model=UserMe)
def me(user: CurrentUser) -> UserMe:
    return UserMe.model_validate(user)


@router.put("/me", response_model=UserMe)
def update_me(
    payload: UpdateProfileRequest, user: CurrentUser, db: DbSession
) -> UserMe:
    """Allow any authenticated user to edit their own profile fields.

    Email change requires the current password (defence against session
    hijack) and a uniqueness check. Role and password are out of scope
    here.
    """
    email_changing = (
        payload.email is not None and payload.email != user.email
    )
    if email_changing:
        if not payload.current_password or not verify_password(
            payload.current_password, user.hashed_password
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="current password required to change email",
            )
        clash = db.scalar(select(User).where(User.email == payload.email))
        if clash and clash.id != user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="email already in use"
            )
        user.email = payload.email
    if payload.name is not None:
        user.name = payload.name
    if payload.last_name is not None:
        user.last_name = payload.last_name
    level_changed = False
    if payload.level is not None and payload.level != user.level:
        # Self-service level changes are an authorization bypass: a user
        # could promote themselves to INSTRUCTOR and unlock the
        # detail-without-filters tone. Only admins manage the seniority
        # axis (via /api/admin/users/{id}/level).
        if user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="el nivel SOC lo asigna un administrador",
            )
        user.level = payload.level
        user.level_approved = True
        level_changed = True
    db.commit()
    db.refresh(user)
    log_audit(
        db,
        actor=user,
        action="auth.update_profile",
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        details={
            "email_changed": email_changing,
            "level_changed": level_changed,
            "level": user.level.value,
        },
    )
    db.commit()
    return UserMe.model_validate(user)


# ── Per-user LLM configuration (BYO Gemini key + preferred model) ───────


def _llm_settings_response(user: User) -> LLMSettingsResponse:
    s = get_settings()
    return LLMSettingsResponse(
        configured=user.gemini_api_key_ciphertext is not None,
        key_last4=user.gemini_key_last4,
        key_validated_at=user.gemini_key_validated_at,
        preferred_chat_model=user.preferred_chat_model,
        available_models=s.chat_models_list,
        default_model=s.gemini_chat_model,
        server_quota_used=user.server_llm_calls_today
        if user.server_llm_quota_date
        and user.server_llm_quota_date == _utc_today()
        else 0,
        server_quota_limit=s.server_llm_daily_quota,
    )


def _utc_today():
    from datetime import UTC, datetime

    return datetime.now(UTC).date()


@router.get("/me/llm", response_model=LLMSettingsResponse)
def get_llm_settings(user: CurrentUser) -> LLMSettingsResponse:
    return _llm_settings_response(user)


@router.put("/me/llm", response_model=LLMSettingsResponse)
def update_llm_settings(
    payload: LLMSettingsUpdate, user: CurrentUser, db: DbSession
) -> LLMSettingsResponse:
    """Set or update the user's BYO key and/or preferred model.

    A new ``api_key`` is validated against Gemini (a tiny generate call)
    BEFORE being persisted, so the user can't save junk and get cryptic
    errors later. Validation failures bubble up as 400/502.
    """
    settings = get_settings()

    # Model preference — must live inside the server allowlist.
    if payload.preferred_chat_model is not None:
        if payload.preferred_chat_model not in settings.chat_models_list:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="model not in allowlist",
            )
        user.preferred_chat_model = payload.preferred_chat_model

    # API key — encrypt + store only after a live ping succeeds.
    if payload.api_key is not None:
        api_key = payload.api_key.strip()
        # Cheap shape check: Google AI Studio keys start with "AIza" and
        # are ~39 chars. Don't be too strict (Google may rotate the
        # format) but reject obvious garbage.
        if len(api_key) < 20:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="api_key looks too short to be a Gemini key",
            )
        try:
            probe = GeminiAdapter(api_key=api_key)
            # Tiny round-trip — 1-token generation is enough to confirm
            # auth works without burning quota.
            probe.generate_text("ping", temperature=0.0)
        except LLMProviderError as exc:
            logger.warning(
                "auth.byo_key_validation_failed",
                extra={"user_id": user.id, "reason": str(exc)},
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Gemini rejected this key — check the value",
            ) from None
        try:
            user.gemini_api_key_ciphertext = encrypt(api_key)
        except EncryptionDisabled as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from None
        user.gemini_key_last4 = last4(api_key)
        from datetime import UTC
        from datetime import datetime as _dt

        user.gemini_key_validated_at = _dt.now(UTC)

    db.commit()
    db.refresh(user)
    log_audit(
        db,
        actor=user,
        action="auth.llm_settings_updated",
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        details={
            "key_changed": payload.api_key is not None,
            "preferred_chat_model": user.preferred_chat_model,
        },
    )
    db.commit()
    return _llm_settings_response(user)


@router.delete("/me/llm", response_model=LLMSettingsResponse)
def clear_llm_key(user: CurrentUser, db: DbSession) -> LLMSettingsResponse:
    """Drop the BYO key. The user goes back to the shared server key
    (subject to the daily quota). Preferred model is preserved."""
    user.gemini_api_key_ciphertext = None
    user.gemini_key_last4 = None
    user.gemini_key_validated_at = None
    db.commit()
    db.refresh(user)
    log_audit(
        db,
        actor=user,
        action="auth.llm_key_cleared",
        target_type="user",
        target_id=user.id,
        target_label=user.email,
    )
    db.commit()
    return _llm_settings_response(user)
