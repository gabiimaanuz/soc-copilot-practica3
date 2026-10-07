"""Password reset token columns on users

«¿Has olvidado tu contraseña?» — stores the SHA-256 of the single-use
token emailed to the user and when it was issued.

Revision ID: 0007_password_reset
Revises: 0006_mfa_totp
Create Date: 2026-10-05 14:00:00 UTC
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_password_reset"
down_revision: str | Sequence[str] | None = "0006_mfa_totp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_reset_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("password_reset_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_password_reset_token_hash", "users", ["password_reset_token_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_users_password_reset_token_hash", table_name="users")
    op.drop_column("users", "password_reset_sent_at")
    op.drop_column("users", "password_reset_token_hash")
