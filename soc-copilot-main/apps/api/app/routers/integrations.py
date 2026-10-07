"""SIEM integrations — Wazuh (Práctica 2, roadmap #1).

Endpoints
---------
POST /api/integrations/wazuh/webhook   ← Wazuh integratord (push). Bearer token.
POST /api/integrations/wazuh/pull      ← admin: pull now from Wazuh Indexer.
GET  /api/integrations/wazuh/status    ← admin: health of both paths.

The webhook is machine-to-machine: it does NOT use the user session cookie
and is authenticated with a shared secret (``WAZUH_WEBHOOK_TOKEN``) compared
in constant time. It has its own rate-limit bucket.
"""
from __future__ import annotations

import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.db import DbSession
from app.middleware.ratelimit import _check, _client_id
from app.models import User
from app.services.audit import log_audit
from app.services.permissions import require_perm
from app.services.wazuh import (
    WazuhPullError,
    ingest_alerts,
    integration_status,
    mark_push_received,
    pull_from_indexer,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations/wazuh", tags=["integrations"])

# 2 MB is plenty for 100 Wazuh alerts and caps memory per request.
_MAX_BODY_BYTES = 2 * 1024 * 1024


def _check_webhook_token(request: Request) -> None:
    settings = get_settings()
    if not settings.wazuh_push_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="wazuh webhook disabled (WAZUH_WEBHOOK_TOKEN not set)",
        )
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token or not hmac.compare_digest(
        token.encode(), settings.wazuh_webhook_token.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid webhook token",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("/webhook", status_code=status.HTTP_202_ACCEPTED)
async def wazuh_webhook(request: Request, db: DbSession) -> dict:
    settings = get_settings()
    _check(
        "wazuh_webhook",
        _client_id(request),
        settings.wazuh_webhook_rate_limit,
        60,
    )
    _check_webhook_token(request)

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="payload too large")
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="payload too large")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="body must be JSON") from None

    # Accept a single alert, a list, or {"alerts": [...]}.
    if isinstance(payload, dict) and isinstance(payload.get("alerts"), list):
        alerts = payload["alerts"]
    elif isinstance(payload, list):
        alerts = payload
    elif isinstance(payload, dict):
        alerts = [payload]
    else:
        raise HTTPException(status_code=400, detail="unsupported payload shape")

    if len(alerts) > settings.wazuh_webhook_max_batch:
        raise HTTPException(
            status_code=413,
            detail=f"max {settings.wazuh_webhook_max_batch} alerts per call",
        )

    # Sync SQLAlchemy work off the event loop.
    result = await run_in_threadpool(ingest_alerts, db, alerts)
    await run_in_threadpool(mark_push_received, db)
    return result.as_dict()


@router.post("/pull")
def wazuh_pull(
    db: DbSession,
    user: User = require_perm("integrations.manage"),
) -> dict:
    try:
        result = pull_from_indexer(db)
    except WazuhPullError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from None
    log_audit(
        db,
        actor=user,
        action="integration.wazuh.pull",
        target_type="integration",
        target_label="wazuh",
        details={k: result[k] for k in ("fetched", "created", "duplicates")},
    )
    db.commit()
    return result


@router.get("/status")
def wazuh_status(
    db: DbSession,
    _user: User = require_perm("integrations.manage"),
) -> dict:
    return integration_status(db)
