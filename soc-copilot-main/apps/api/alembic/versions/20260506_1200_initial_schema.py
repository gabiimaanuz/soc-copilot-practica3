"""initial schema

Captures the schema produced by app.db.init_db() through Phase 5
(users, alerts, recommendations, audit_logs, role_permissions + the
user_role enum and BYO Gemini / quota columns).

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-06 12:00:00 UTC
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    user_role = postgresql.ENUM("ANALYST", "ADMIN", name="user_role")
    user_role.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "name",
            sa.String(100),
            nullable=False,
            server_default=sa.text("'Analista'"),
        ),
        sa.Column(
            "last_name",
            sa.String(100),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column(
            "password_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "role",
            postgresql.ENUM(
                "ANALYST", "ADMIN", name="user_role", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("gemini_api_key_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("gemini_key_last4", sa.String(8), nullable=True),
        sa.Column(
            "gemini_key_validated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("preferred_chat_model", sa.String(64), nullable=True),
        sa.Column(
            "server_llm_calls_today",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("server_llm_quota_date", sa.Date(), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("log", sa.Text(), nullable=False),
        sa.Column("source", sa.String(200), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(16), nullable=True),
        sa.Column(
            "mitre_techniques", postgresql.ARRAY(sa.String(32)), nullable=True
        ),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_alerts_user_id", "alerts", ["user_id"])

    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "alert_id",
            sa.Integer(),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actions", postgresql.JSONB(), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("learning_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_recommendations_alert_id", "recommendations", ["alert_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_email", sa.String(255), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("target_label", sa.String(255), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])

    op.create_table(
        "role_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "role",
            postgresql.ENUM(
                "ANALYST", "ADMIN", name="user_role", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("permission_key", sa.String(64), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("role", "permission_key", name="uq_role_perm"),
    )
    op.create_index("ix_role_permissions_role", "role_permissions", ["role"])
    op.create_index(
        "ix_role_permissions_permission_key",
        "role_permissions",
        ["permission_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_role_permissions_permission_key", table_name="role_permissions")
    op.drop_index("ix_role_permissions_role", table_name="role_permissions")
    op.drop_table("role_permissions")

    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_recommendations_alert_id", table_name="recommendations")
    op.drop_table("recommendations")

    op.drop_index("ix_alerts_user_id", table_name="alerts")
    op.drop_table("alerts")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    postgresql.ENUM(name="user_role").drop(op.get_bind(), checkfirst=True)
