"""Migration bridge test.

Verifies the `init_db()` Alembic bridge: when a Postgres DB has tables that
were created by the legacy `Base.metadata.create_all + ALTER TABLE` path
(i.e. before Alembic existed) but no `alembic_version` row, init_db must
*stamp* head rather than try to *upgrade* (which would fail trying to
recreate existing tables).

Skipped offline; the e2e job in .github/workflows/e2e.yml runs it against
the postgres service container alongside the rest of the e2e suite.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import text

if os.environ.get("RUN_E2E") != "1":  # pragma: no cover
    pytest.skip("Migration bridge test skipped (set RUN_E2E=1)", allow_module_level=True)

from app.db import Base, _engine, init_db


def _reset_schema() -> None:
    """Wipe public schema so each scenario starts from a known empty state.

    `dispose()` first so any idle pool connections (e.g. from a prior test
    that hit the API via TestClient) don't hold locks that would block the
    DROP SCHEMA.
    """
    _engine.dispose()
    with _engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


def _alembic_version() -> str | None:
    with _engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT version_num FROM alembic_version "
                "WHERE 'alembic_version' IN "
                "(SELECT tablename FROM pg_tables WHERE schemaname='public')"
            )
        ).fetchall()
    return rows[0][0] if rows else None


def test_bridge_stamps_existing_unmanaged_db():
    """Tables exist but alembic_version doesn't → init_db must stamp head."""
    _reset_schema()

    # Simulate the legacy code path: schema created by SQLAlchemy directly.
    from app import models  # noqa: F401  (registers tables)
    Base.metadata.create_all(bind=_engine)

    with _engine.begin() as conn:
        existing = {
            r[0]
            for r in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            ).fetchall()
        }
    assert "users" in existing
    assert "alembic_version" not in existing

    # The bridge should detect this and stamp instead of upgrading.
    init_db()

    assert _alembic_version() == "0001_initial"


def test_upgrade_runs_on_empty_db():
    """No tables at all → init_db must run the migration end-to-end."""
    _reset_schema()

    init_db()

    with _engine.begin() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            ).fetchall()
        }
    # Schema is in place.
    assert {"users", "alerts", "recommendations", "audit_logs", "role_permissions"} <= tables
    assert _alembic_version() == "0001_initial"


def test_idempotent_on_already_migrated_db():
    """alembic_version already at head → second init_db must be a no-op."""
    # Leaves the DB at head from the previous test; calling again must not raise.
    init_db()
    assert _alembic_version() == "0001_initial"
