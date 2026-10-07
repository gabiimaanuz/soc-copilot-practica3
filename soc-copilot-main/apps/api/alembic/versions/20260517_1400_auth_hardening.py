"""auth hardening: email verification, lockout, seniority level

Adds the columns introduced for the security pass on /auth/register and
/auth/login:

* ``users.level`` — SOC seniority axis (L1 / L2 / INSTRUCTOR), orthogonal
  to ``role``. Drives Copilot tone.
* Email verification: ``is_verified``, ``email_verification_token``,
  ``email_verification_sent_at``, ``email_verified_at``.
* Brute-force lockout: ``failed_login_attempts``, ``locked_until``.

Revision ID: 0002_auth_hardening
Revises: 0001_initial
Create Date: 2026-05-17 14:00:00 UTC
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_auth_hardening"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    user_level = postgresql.ENUM("L1", "L2", "INSTRUCTOR", name="user_level")
    user_level.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "users",
        sa.Column(
            "level",
            postgresql.ENUM(
                "L1", "L2", "INSTRUCTOR", name="user_level", create_type=False
            ),
            nullable=False,
            server_default="L1",
        ),
    )

    op.add_column(
        "users",
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("email_verification_token", sa.String(64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_verification_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_users_email_verification_token",
        "users",
        ["email_verification_token"],
    )

    op.add_column(
        "users",
        sa.Column(
            "failed_login_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )

    # Legacy rows: mark every pre-existing user as already verified so
    # the new gate doesn't lock them out the moment it's flipped on.
    op.execute(
        "UPDATE users SET is_verified = true, email_verified_at = now() "
        "WHERE is_verified = false"
    )


def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
    op.drop_index(
        "ix_users_email_verification_token", table_name="users"
    )
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "email_verification_sent_at")
    op.drop_column("users", "email_verification_token")
    op.drop_column("users", "is_verified")
    op.drop_column("users", "level")

    postgresql.ENUM(name="user_level").drop(op.get_bind(), checkfirst=True)
