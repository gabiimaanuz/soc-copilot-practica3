"""SQLAlchemy session factory + Base.

Schema is managed by Alembic. `init_db()` runs `alembic upgrade head` against
the configured Postgres URL on startup. SQLite (used in some unit tests) keeps
using `Base.metadata.create_all` since Alembic migrations contain Postgres-only
types (JSONB, ARRAY, ENUM).
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

_settings = get_settings()
_engine = create_engine(_settings.database_url, pool_pre_ping=True, future=True)
_SessionLocal = sessionmaker(
    bind=_engine, autoflush=False, autocommit=False, future=True
)

_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a request-scoped DB session."""
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Bring the DB schema up to head.

    Postgres → run Alembic migrations (`alembic upgrade head`). All schema
    changes from now on must ship as a new revision under `alembic/versions/`.

    SQLite → fall back to `Base.metadata.create_all`. The Alembic scripts use
    Postgres-only types and are not portable; SQLite is only used by offline
    unit tests, where matching the production schema exactly is not required.
    """
    from app import models  # noqa: F401  (registers tables on Base.metadata)

    if _engine.dialect.name == "postgresql":
        from sqlalchemy import inspect

        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", _settings.database_url)

        # Bridge for DBs that were created by the old `create_all + ALTER`
        # path: tables exist but alembic_version doesn't. Stamp head so the
        # next deploy starts tracking revisions instead of trying to recreate.
        inspector = inspect(_engine)
        existing = set(inspector.get_table_names())
        if "users" in existing and "alembic_version" not in existing:
            command.stamp(cfg, "head")
        else:
            command.upgrade(cfg, "head")
    else:
        Base.metadata.create_all(bind=_engine)


# FastAPI dependency alias — avoids `Depends(get_db)` in defaults (B008).
DbSession = Annotated[Session, Depends(get_db)]
