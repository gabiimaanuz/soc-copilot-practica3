"""Runtime-mutable settings backed by the app_settings table.

The DB row wins over environment variables: this lets admins toggle a
flag from the UI without redeploying. Functions in this module are the
single source of truth — never read ``settings.allow_public_registration``
directly from a route handler, go through ``is_public_registration_enabled``.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppSetting, User

# ─── keys ───────────────────────────────────────────────────────────────
PUBLIC_REGISTRATION_KEY = "public_registration_enabled"


def _get_bool(db: Session, key: str) -> bool | None:
    row = db.get(AppSetting, key)
    if row is None:
        return None
    return row.value.strip().lower() in {"1", "true", "yes", "on"}


def _set_bool(db: Session, key: str, value: bool, actor: User | None) -> None:
    row = db.get(AppSetting, key)
    str_value = "true" if value else "false"
    if row is None:
        row = AppSetting(
            key=key,
            value=str_value,
            updated_by=actor.id if actor else None,
        )
        db.add(row)
    else:
        row.value = str_value
        row.updated_at = datetime.now(UTC)
        row.updated_by = actor.id if actor else None
    db.commit()


# ─── public registration toggle ─────────────────────────────────────────


def is_public_registration_enabled(db: Session) -> bool:
    """Return whether self-service registration is currently open.

    DB row wins. If unset, fall back to the env-derived setting so the
    deploy keeps its bootstrap default.
    """
    override = _get_bool(db, PUBLIC_REGISTRATION_KEY)
    if override is not None:
        return override
    return get_settings().allow_public_registration


def set_public_registration_enabled(
    db: Session, value: bool, actor: User | None
) -> None:
    _set_bool(db, PUBLIC_REGISTRATION_KEY, value, actor)
