"""MFA / TOTP columns on users

Práctica 2 · mejora 8.2 — segundo factor obligatorio para todos.

* ``mfa_enabled``            enrolment completed
* ``mfa_secret_ciphertext``  TOTP secret encrypted with Fernet
* ``mfa_enabled_at``         when enrolment completed
* ``mfa_last_used_step``     last accepted 30 s step (anti-replay)
* ``mfa_recovery_codes``     SHA-256 hashes of unused recovery codes

Existing users start with ``mfa_enabled = false`` and are forced through
enrolment on their next login.

Revision ID: 0006_mfa_totp
Revises: 0005_wazuh_integration
Create Date: 2026-10-05 13:00:00 UTC
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_mfa_totp"
down_revision: str | Sequence[str] | None = "0005_wazuh_integration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "mfa_enabled", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "users", sa.Column("mfa_secret_ciphertext", sa.LargeBinary(), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("mfa_enabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users", sa.Column("mfa_last_used_step", sa.Integer(), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column(
            "mfa_recovery_codes",
            postgresql.JSONB(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "mfa_recovery_codes")
    op.drop_column("users", "mfa_last_used_step")
    op.drop_column("users", "mfa_enabled_at")
    op.drop_column("users", "mfa_secret_ciphertext")
    op.drop_column("users", "mfa_enabled")
