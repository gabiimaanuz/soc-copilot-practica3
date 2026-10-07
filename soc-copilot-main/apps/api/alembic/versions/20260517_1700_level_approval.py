"""level approval flow

Adds admin gating around the SOC seniority axis introduced in
0002_auth_hardening:

* ``users.requested_level`` — the level the user picked at registration
  (kept for admin context).
* ``users.level_approved`` — until an admin sets the level, the user is
  pinned to L1; the value the user picked is stored in
  ``requested_level`` and surfaced in the admin UI.

Pre-existing rows are marked as already approved so this rollout is
backwards-compatible.

Revision ID: 0003_level_approval
Revises: 0002_auth_hardening
Create Date: 2026-05-17 17:00:00 UTC
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_level_approval"
down_revision: str | Sequence[str] | None = "0002_auth_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "requested_level",
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
            "level_approved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Backfill: every existing user keeps the level they already had and
    # is treated as already approved so the new gate doesn't suddenly
    # demote anyone to L1.
    op.execute(
        "UPDATE users SET requested_level = level, level_approved = true"
    )


def downgrade() -> None:
    op.drop_column("users", "level_approved")
    op.drop_column("users", "requested_level")
