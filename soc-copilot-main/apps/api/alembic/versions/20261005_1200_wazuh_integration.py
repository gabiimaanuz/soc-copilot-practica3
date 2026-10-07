"""Wazuh SIEM integration columns on alerts

Adds the fields needed to ingest alerts from Wazuh (push via webhook and
pull from the Wazuh Indexer) and to keep them deduplicated:

* ``origin``       manual | wazuh (plain string, indexed)
* ``external_id``  Wazuh alert id, unique together with origin
* ``rule_level``   Wazuh rule.level (0-15)
* ``agent_name``   Wazuh agent that raised the alert
* ``event_at``     event timestamp in the SIEM
* ``analyzed_at``  when the AI analysis ran (NULL = pending triage)

Existing rows are manual alerts that were analysed at creation time, so
``analyzed_at`` is backfilled with ``created_at``.

Revision ID: 0005_wazuh_integration
Revises: 0004_app_settings
Create Date: 2026-10-05 12:00:00 UTC
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_wazuh_integration"
down_revision: str | Sequence[str] | None = "0004_app_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "alerts",
        sa.Column(
            "origin",
            sa.String(length=16),
            nullable=False,
            server_default="manual",
        ),
    )
    op.add_column(
        "alerts", sa.Column("external_id", sa.String(length=128), nullable=True)
    )
    op.add_column("alerts", sa.Column("rule_level", sa.Integer(), nullable=True))
    op.add_column(
        "alerts", sa.Column("agent_name", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "alerts",
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_alerts_origin", "alerts", ["origin"])
    op.create_unique_constraint(
        "uq_alert_origin_external", "alerts", ["origin", "external_id"]
    )
    op.execute("UPDATE alerts SET analyzed_at = created_at WHERE analyzed_at IS NULL")


def downgrade() -> None:
    op.drop_constraint("uq_alert_origin_external", "alerts", type_="unique")
    op.drop_index("ix_alerts_origin", table_name="alerts")
    op.drop_column("alerts", "analyzed_at")
    op.drop_column("alerts", "event_at")
    op.drop_column("alerts", "agent_name")
    op.drop_column("alerts", "rule_level")
    op.drop_column("alerts", "external_id")
    op.drop_column("alerts", "origin")
