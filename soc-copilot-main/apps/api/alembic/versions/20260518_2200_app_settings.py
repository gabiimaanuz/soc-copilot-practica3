"""app_settings key/value store

Adds a tiny key/value table for runtime-mutable flags (e.g. opening or
closing public registration without restarting the API). The first row
seeded is ``public_registration_enabled``, which lets admins toggle the
flag from the UI.

The DB row takes precedence over the ``ALLOW_PUBLIC_REGISTRATION``
environment variable; if no row exists the env var is the fallback so
the deploy keeps the same behaviour it had before this migration.

Revision ID: 0004_app_settings
Revises: 0003_level_approval
Create Date: 2026-05-18 22:00:00 UTC
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_app_settings"
down_revision: str | Sequence[str] | None = "0003_level_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.String(length=1024), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
