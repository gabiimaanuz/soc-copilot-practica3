"""Audit log helper.

Wraps inserts into the `audit_logs` table. Callers pass the actor (current
admin User), an action verb, and optionally a target + free-form details
dict. The DB session is flushed but NOT committed by this function — the
caller's outer transaction owns the commit so the audit row only persists if
the action it describes also persisted.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, User

logger = logging.getLogger(__name__)


def log_audit(
    db: Session,
    *,
    actor: User | None = None,
    actor_id: int | None = None,
    actor_email: str | None = None,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    target_label: str | None = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    ip: str | None = None
    if request is not None and request.client is not None:
        ip = request.client.host

    final_actor_id = actor.id if actor else actor_id
    final_actor_email = actor.email if actor else (actor_email or "system")

    entry = AuditLog(
        actor_id=final_actor_id,
        actor_email=final_actor_email,
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_label=target_label,
        details=details,
        ip=ip,
    )
    db.add(entry)
    db.flush()
    logger.info(
        action,
        extra={
            "actor_id": final_actor_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
        },
    )
    return entry
