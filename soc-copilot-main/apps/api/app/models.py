"""SQLAlchemy ORM models."""
from __future__ import annotations

from datetime import UTC, date, datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class UserRole(str, Enum):
    ANALYST = "analyst"
    ADMIN = "admin"


class UserLevel(str, Enum):
    """SOC seniority axis, orthogonal to RBAC role.

    Drives Copilot tone & depth (L1 gets more guidance, L2 gets terser
    output, INSTRUCTOR gets unfiltered detail). Not used for RBAC — see
    ``UserRole`` for that.
    """

    L1 = "L1"
    L2 = "L2"
    INSTRUCTOR = "INSTRUCTOR"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default="Analista"
    )
    last_name: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default=""
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    # Bumped whenever the password is changed; embedded as `pv` in JWTs and
    # re-checked on every authenticated request, so old tokens stop working
    # after a reset (e.g. admin-forced password change).
    password_version: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default="0"
    )
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role"),
        nullable=False,
        default=UserRole.ANALYST,
    )
    level: Mapped[UserLevel] = mapped_column(
        SAEnum(UserLevel, name="user_level"),
        nullable=False,
        default=UserLevel.L1,
        server_default=UserLevel.L1.value,
    )
    # What the user picked at registration. Kept separate from ``level``
    # so the admin can see the user's self-assessment without trusting it
    # for authorization. ``level`` is forced to L1 at register and only
    # promoted when an admin approves the account.
    requested_level: Mapped[UserLevel] = mapped_column(
        SAEnum(UserLevel, name="user_level"),
        nullable=False,
        default=UserLevel.L1,
        server_default=UserLevel.L1.value,
    )
    # Flips to True once an admin sets the seniority level. Until then
    # the user is pinned to L1 and the level selector in /profile is
    # read-only.
    level_approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
    )

    # ── Email verification ──────────────────────────────────────────────
    # is_verified gates login when settings.auth_require_email_verification
    # is on. Bootstrap admin is auto-verified. Token is a urlsafe 32-byte
    # random string, valid for settings.email_verification_ttl_hours.
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    email_verification_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    email_verification_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Brute-force lockout ─────────────────────────────────────────────
    # Counter resets on successful login. When failed_login_attempts hits
    # settings.auth_lockout_threshold, locked_until is set N minutes ahead
    # and /auth/login refuses even with the right password until it passes.
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── BYO Gemini key (optional) ───────────────────────────────────────
    # Encrypted with Fernet (APP_ENCRYPTION_KEY). NULL = user is on the
    # shared server key and subject to the daily quota below.
    gemini_api_key_ciphertext: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    # Last 4 chars of the cleartext key, kept so the UI can show
    # "•••••FpMpY" without ever round-tripping the secret.
    gemini_key_last4: Mapped[str | None] = mapped_column(String(8), nullable=True)
    gemini_key_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Per-user default model; falls back to GEMINI_CHAT_MODEL when null.
    # Validated against the server allowlist before saving.
    preferred_chat_model: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    # ── Server-key quota tracking ───────────────────────────────────────
    # Counts only LLM calls that consumed the SHARED server key. Resets
    # daily (UTC). When user has their own key these stay at 0.
    server_llm_calls_today: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    server_llm_quota_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )

    # ── Password reset (Práctica 2) ─────────────────────────────────────
    # Only the SHA-256 of the emailed token is stored, so a DB leak can't
    # be used to reset passwords. Single use: cleared on success.
    password_reset_token_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    password_reset_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── MFA / TOTP (Práctica 2) ─────────────────────────────────────────
    # Secret encrypted with Fernet (APP_ENCRYPTION_KEY). Set at enrolment
    # start; ``mfa_enabled`` flips to True only after the first valid code.
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    mfa_secret_ciphertext: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Last accepted TOTP time-step (anti-replay).
    mfa_last_used_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # SHA-256 hashes of the unused recovery codes.
    mfa_recovery_codes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    alerts: Mapped[list[Alert]] = relationship(back_populates="user")


class AlertOrigin(str, Enum):
    """Where an alert came from.

    ``manual`` = pasted by an analyst in the Alert Explainer.
    ``wazuh``  = ingested from the Wazuh SIEM (webhook push or indexer pull).
    Stored as a plain string column so new SIEMs don't need an enum migration.
    """

    MANUAL = "manual"
    WAZUH = "wazuh"


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        # Dedupe SIEM alerts: the same Wazuh alert can arrive twice (push +
        # pull, or integratord retries). NULL external_id (manual alerts)
        # never collides because Postgres treats NULLs as distinct.
        UniqueConstraint("origin", "external_id", name="uq_alert_origin_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    log: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(String(200))

    # ── SIEM ingestion (Práctica 2) ─────────────────────────────────────
    origin: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=AlertOrigin.MANUAL.value,
        server_default=AlertOrigin.MANUAL.value,
        index=True,
    )
    # Wazuh alert id (e.g. "1717171717.123456"). Unique per origin.
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Wazuh rule.level (0-15). Null for manual alerts.
    rule_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Timestamp of the event in the SIEM (not ingestion time).
    event_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # When the AI analysis ran. NULL = SIEM alert still pending triage.
    analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Output of /api/explain (filled when alert is created via that endpoint)
    summary: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str | None] = mapped_column(String(16))
    mitre_techniques: Mapped[list[str] | None] = mapped_column(ARRAY(String(32)))
    reasoning: Mapped[str | None] = mapped_column(Text)

    # Nullable FK so legacy rows (created before Phase 4) survive without
    # an owner; admin can see them, analysts cannot.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
    )

    user: Mapped[User | None] = relationship(back_populates="alerts")
    recommendations: Mapped[list[Recommendation]] = relationship(
        back_populates="alert",
        cascade="all, delete-orphan",
    )


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # JSONB list of {title, detail, rationale}
    actions: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    learning_notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
    )

    alert: Mapped[Alert] = relationship(back_populates="recommendations")


class AuditLog(Base):
    """Append-only audit trail for admin actions.

    Rows are written from helper `services.audit.log_audit`. We never delete
    or update them; the table is treated as immutable. `actor_id` is nullable
    so log entries survive after the actor account is deleted.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_email: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[int | None] = mapped_column()
    target_label: Mapped[str | None] = mapped_column(String(255))
    details: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))


class AppSetting(Base):
    """Tiny key/value store for runtime-mutable feature flags.

    Used for settings that must change without redeploying — currently
    ``public_registration_enabled``. Each row represents a single flag;
    the value is stored as a string and parsed by the caller (``"true"``
    / ``"false"`` for booleans). The DB row wins over any matching
    environment variable; absence of a row falls back to the env value.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(1024), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class RolePermission(Base):
    """Per-role override of a permission key.

    Rows are seeded on init_db from the static registry in
    services.permissions. Admins flip them through PUT /api/admin/permissions.
    Absence of a row means "fall back to the registry default", so the table
    only stores deviations.
    """

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role", "permission_key", name="uq_role_perm"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role"), nullable=False, index=True
    )
    permission_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
