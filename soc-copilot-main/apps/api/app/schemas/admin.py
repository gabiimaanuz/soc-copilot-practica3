from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import UserLevel, UserRole
from app.services.password import MAX_LENGTH, MIN_LENGTH, check_password


def _enforce_password_policy(v: str) -> str:
    # Same rules as RegisterRequest so admin-side flows (reset password,
    # create user) cannot bypass the strength policy that the UI enforces.
    result = check_password(v)
    if not result.ok:
        raise ValueError(result.first_error())
    return v


class ChangePasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=MIN_LENGTH, max_length=MAX_LENGTH)

    @field_validator("new_password")
    @classmethod
    def _strong_password(cls, v: str) -> str:
        return _enforce_password_policy(v)


class ChangeRoleRequest(BaseModel):
    role: UserRole


class ChangeLevelRequest(BaseModel):
    level: UserLevel


class CreateUserRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=MIN_LENGTH, max_length=MAX_LENGTH)
    role: UserRole = UserRole.ANALYST
    level: UserLevel = UserLevel.L1

    @field_validator("password")
    @classmethod
    def _strong_password(cls, v: str) -> str:
        return _enforce_password_policy(v)


class PermissionCell(BaseModel):
    permission_key: str
    area: str
    action: str
    role: UserRole
    allowed: bool
    locked: bool
    default: bool


class PermissionChange(BaseModel):
    role: UserRole
    permission_key: str
    allowed: bool


class UpdatePermissionsRequest(BaseModel):
    changes: list[PermissionChange] = Field(..., min_length=1)


class AdminUserView(BaseModel):
    """Admin-facing view of a user — adds quota + BYO-key fields on top of UserMe.

    Kept separate from UserMe so GET /api/auth/me doesn't leak internal counters
    to non-admin sessions.
    """

    id: int
    name: str
    last_name: str
    email: str
    role: UserRole
    level: UserLevel
    requested_level: UserLevel
    level_approved: bool
    created_at: datetime
    server_llm_calls_today: int
    server_llm_quota_date: date | None
    server_llm_quota_limit: int
    byo_key_configured: bool
    gemini_key_last4: str | None
    mfa_enabled: bool = False


class AppSettingsView(BaseModel):
    """Snapshot of runtime-mutable settings, served to the admin panel."""

    public_registration_enabled: bool


class UpdatePublicRegistrationRequest(BaseModel):
    enabled: bool


class AuditLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    actor_id: int | None
    actor_email: str
    action: str
    target_type: str | None
    target_id: int | None
    target_label: str | None
    details: dict[str, Any] | None
    ip: str | None
