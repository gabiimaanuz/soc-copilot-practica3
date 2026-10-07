import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.config import get_settings
from app.db import DbSession
from app.models import AuditLog, User, UserRole
from app.schemas.admin import (
    AdminUserView,
    AppSettingsView,
    AuditLogEntry,
    ChangeLevelRequest,
    ChangePasswordRequest,
    ChangeRoleRequest,
    CreateUserRequest,
    PermissionCell,
    UpdatePermissionsRequest,
    UpdatePublicRegistrationRequest,
)
from app.schemas.auth import UserMe
from app.services.audit import log_audit
from app.services.auth import hash_password
from app.services.permissions import (
    is_allowed,
    list_effective,
    require_perm,
    set_permission,
)
from app.services.settings import (
    is_public_registration_enabled,
    set_public_registration_enabled,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


def _count_admins(db) -> int:
    return db.scalar(
        select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
    ) or 0


def _to_admin_view(u: User, *, today, quota_limit: int) -> AdminUserView:
    """Build an AdminUserView, normalising the daily counter to 0 when the
    stored quota date isn't today (mirrors auth._llm_settings_response)."""
    calls_today = (
        u.server_llm_calls_today
        if u.server_llm_quota_date and u.server_llm_quota_date == today
        else 0
    )
    return AdminUserView(
        id=u.id,
        name=u.name,
        last_name=u.last_name,
        email=u.email,
        role=u.role,
        level=u.level,
        requested_level=u.requested_level,
        level_approved=u.level_approved,
        created_at=u.created_at,
        server_llm_calls_today=calls_today,
        server_llm_quota_date=u.server_llm_quota_date,
        server_llm_quota_limit=quota_limit,
        byo_key_configured=u.gemini_api_key_ciphertext is not None,
        gemini_key_last4=u.gemini_key_last4,
        mfa_enabled=bool(u.mfa_enabled),
    )


@router.get("/users", response_model=list[AdminUserView])
def list_users(
    db: DbSession,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = require_perm("users.list"),
) -> list[AdminUserView]:
    """List all users with admin-only quota and BYO-key metadata."""
    settings = get_settings()
    today = datetime.now(UTC).date()
    quota_limit = settings.server_llm_daily_quota
    rows = db.scalars(select(User).order_by(User.id).offset(offset).limit(limit))
    return [_to_admin_view(u, today=today, quota_limit=quota_limit) for u in rows]


@router.post("/users", response_model=UserMe, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest,
    db: DbSession,
    request: Request,
    user: User = require_perm("users.create"),
) -> User:
    """Create a user with an explicit role (Admin only)."""
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already registered"
        )

    # Admin-created users are pre-verified — the admin vouches for them.
    # The level is assigned directly by the admin, so it counts as
    # already approved (no review queue step needed).
    new_user = User(
        name=payload.name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        level=payload.level,
        requested_level=payload.level,
        level_approved=True,
        is_verified=True,
        email_verified_at=datetime.now(UTC),
    )
    db.add(new_user)
    db.flush()

    log_audit(
        db,
        actor=user,
        action="user.create",
        target_type="user",
        target_id=new_user.id,
        target_label=new_user.email,
        details={"role": new_user.role.value, "name": new_user.name},
        request=request,
    )
    db.commit()
    db.refresh(new_user)
    return new_user


@router.put("/users/{user_id}/password", status_code=status.HTTP_200_OK)
def change_user_password(
    user_id: int,
    payload: ChangePasswordRequest,
    db: DbSession,
    request: Request,
    user: User = require_perm("users.update_password"),
) -> dict:
    """Change the password of any user (Admin only).

    Bumping `password_version` invalidates every JWT issued before this
    moment for the target user, so a forced reset takes effect immediately
    even on already-logged-in sessions.
    """
    target_user = db.scalar(select(User).where(User.id == user_id))
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user not found"
        )

    target_user.hashed_password = hash_password(payload.new_password)
    target_user.password_version = (target_user.password_version or 0) + 1

    log_audit(
        db,
        actor=user,
        action="user.password_reset",
        target_type="user",
        target_id=target_user.id,
        target_label=target_user.email,
        request=request,
    )
    db.commit()

    return {"status": "ok", "message": "password updated successfully"}


@router.post("/users/{user_id}/reset-llm-quota", status_code=status.HTTP_200_OK)
def reset_llm_quota(
    user_id: int,
    db: DbSession,
    request: Request,
    user: User = require_perm("users.reset_llm_quota"),
) -> dict:
    """Reset a user's daily quota on the SHARED server LLM key.

    Useful when an analyst gets blocked by the per-day budget and an admin
    decides to grant a fresh allocation (e.g. during an incident drill).
    Doesn't touch BYO keys — only the counter against the shared key.
    """
    target = db.scalar(select(User).where(User.id == user_id))
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user not found"
        )
    previous = target.server_llm_calls_today
    target.server_llm_calls_today = 0
    # Leave server_llm_quota_date pointing to today so the next call
    # doesn't trigger a "rolled to a new day" reset path.
    log_audit(
        db,
        actor=user,
        action="user.llm_quota_reset",
        target_type="user",
        target_id=target.id,
        target_label=target.email,
        details={"previous_count": previous},
        request=request,
    )
    db.commit()
    return {
        "status": "ok",
        "user_id": target.id,
        "previous_count": previous,
    }


@router.post("/users/{user_id}/mfa/reset", status_code=status.HTTP_200_OK)
def reset_user_mfa(
    user_id: int,
    db: DbSession,
    request: Request,
    user: User = require_perm("users.reset_mfa"),
) -> dict:
    """Práctica 2 · MFA: wipe a user's TOTP enrolment (lost phone).

    The user must enrol again on next login. ``password_version`` is bumped
    so every open session of that user is invalidated immediately.
    """
    target = db.scalar(select(User).where(User.id == user_id))
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    was_enabled = bool(target.mfa_enabled)
    target.mfa_enabled = False
    target.mfa_secret_ciphertext = None
    target.mfa_enabled_at = None
    target.mfa_last_used_step = None
    target.mfa_recovery_codes = None
    target.password_version = (target.password_version or 0) + 1
    log_audit(
        db,
        actor=user,
        action="user.mfa_reset",
        target_type="user",
        target_id=target.id,
        target_label=target.email,
        details={"was_enabled": was_enabled},
        request=request,
    )
    db.commit()
    return {"status": "ok", "user_id": target.id, "was_enabled": was_enabled}


@router.put("/users/{user_id}/role", response_model=UserMe)
def change_user_role(
    user_id: int,
    payload: ChangeRoleRequest,
    db: DbSession,
    request: Request,
    user: User = require_perm("users.update_role"),
) -> User:
    """Change a user's role (Admin only).

    Refuses to demote the last remaining admin and refuses to demote the
    actor themselves. Bumps `password_version` so existing sessions pick up
    the new role on the next request.
    """
    target_user = db.scalar(select(User).where(User.id == user_id))
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user not found"
        )

    if target_user.role == payload.role:
        return target_user

    demoting_admin = (
        target_user.role == UserRole.ADMIN and payload.role != UserRole.ADMIN
    )
    if demoting_admin:
        if target_user.id == user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cannot demote yourself",
            )
        if _count_admins(db) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cannot demote the last admin",
            )

    old_role = target_user.role.value
    target_user.role = payload.role
    target_user.password_version = (target_user.password_version or 0) + 1

    log_audit(
        db,
        actor=user,
        action="user.role_change",
        target_type="user",
        target_id=target_user.id,
        target_label=target_user.email,
        details={"from": old_role, "to": payload.role.value},
        request=request,
    )
    db.commit()
    db.refresh(target_user)
    return target_user


@router.put("/users/{user_id}/level", response_model=AdminUserView)
def change_user_level(
    user_id: int,
    payload: ChangeLevelRequest,
    db: DbSession,
    request: Request,
    user: User = require_perm("users.update_level"),
) -> AdminUserView:
    """Assign a SOC seniority level to a user and mark it approved.

    New self-registered users sit at L1 with ``level_approved=false``
    until an admin reviews their ``requested_level`` and calls this
    endpoint to confirm or override it.
    """
    target = db.scalar(select(User).where(User.id == user_id))
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user not found"
        )
    old_level = target.level.value
    was_approved = target.level_approved
    target.level = payload.level
    target.level_approved = True

    log_audit(
        db,
        actor=user,
        action="user.level_change",
        target_type="user",
        target_id=target.id,
        target_label=target.email,
        details={
            "from": old_level,
            "to": payload.level.value,
            "was_pending": not was_approved,
            "requested": target.requested_level.value,
        },
        request=request,
    )
    db.commit()
    db.refresh(target)
    settings = get_settings()
    today = datetime.now(UTC).date()
    return _to_admin_view(
        target, today=today, quota_limit=settings.server_llm_daily_quota
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: DbSession,
    request: Request,
    user: User = require_perm("users.delete"),
) -> None:
    """Delete a user (Admin only).

    Refuses to delete the actor themselves or the last remaining admin.
    Owned alerts have `user_id` set NULL via the FK ON DELETE rule.
    """
    target_user = db.scalar(select(User).where(User.id == user_id))
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user not found"
        )
    if target_user.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot delete yourself",
        )
    if target_user.role == UserRole.ADMIN and _count_admins(db) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot delete the last admin",
        )

    target_email = target_user.email
    target_id = target_user.id
    target_role = target_user.role.value
    db.delete(target_user)

    log_audit(
        db,
        actor=user,
        action="user.delete",
        target_type="user",
        target_id=target_id,
        target_label=target_email,
        details={"role": target_role},
        request=request,
    )
    db.commit()


@router.get("/audit", response_model=list[AuditLogEntry])
def list_audit(
    db: DbSession,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: str | None = Query(None, description="Filter by exact action verb"),
    actor_email: str | None = Query(
        None, description="Substring match on actor_email"
    ),
    user: User = require_perm("audit.view"),
) -> list[AuditLog]:
    """Return audit log entries, newest first."""
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_email:
        stmt = stmt.where(AuditLog.actor_email.ilike(f"%{actor_email}%"))
    stmt = stmt.offset(offset).limit(limit)
    return list(db.scalars(stmt))


@router.get("/permissions", response_model=list[PermissionCell])
def get_permissions(
    db: DbSession,
    user: User = require_perm("permissions.manage"),
) -> list[dict]:
    """Return the full role x permission matrix with current effective values."""
    return list_effective(db)


@router.put("/permissions", response_model=list[PermissionCell])
def update_permissions(
    payload: UpdatePermissionsRequest,
    db: DbSession,
    request: Request,
    user: User = require_perm("permissions.manage"),
) -> list[dict]:
    """Bulk-update permission cells. Each item flips one (role, key) bit."""
    changes: list[dict] = []
    for change in payload.changes:
        before = is_allowed(db, change.role, change.permission_key)
        set_permission(db, change.role, change.permission_key, change.allowed)
        if before != change.allowed:
            changes.append(
                {
                    "role": change.role.value,
                    "permission_key": change.permission_key,
                    "from": before,
                    "to": change.allowed,
                }
            )

    if changes:
        log_audit(
            db,
            actor=user,
            action="permissions.update",
            target_type="role_permissions",
            details={"changes": changes},
            request=request,
        )
    db.commit()
    return list_effective(db)


# ─── runtime-mutable settings ──────────────────────────────────────────


@router.get("/settings", response_model=AppSettingsView)
def get_app_settings(
    db: DbSession,
    user: User = require_perm("permissions.manage"),
) -> AppSettingsView:
    """Return current values of admin-toggleable flags."""
    return AppSettingsView(
        public_registration_enabled=is_public_registration_enabled(db),
    )


@router.put("/settings/public-registration", response_model=AppSettingsView)
def update_public_registration(
    payload: UpdatePublicRegistrationRequest,
    db: DbSession,
    request: Request,
    user: User = require_perm("permissions.manage"),
) -> AppSettingsView:
    """Open or close self-service registration.

    The change is immediate — no API restart required. We persist the
    new value in ``app_settings`` (which shadows the env-var default)
    and write an audit row so the toggle is traceable.
    """
    before = is_public_registration_enabled(db)
    set_public_registration_enabled(db, payload.enabled, actor=user)
    if before != payload.enabled:
        log_audit(
            db,
            actor=user,
            action="settings.public_registration.update",
            target_type="app_settings",
            target_label="public_registration_enabled",
            details={"from": before, "to": payload.enabled},
            request=request,
        )
        db.commit()
    return AppSettingsView(public_registration_enabled=payload.enabled)
