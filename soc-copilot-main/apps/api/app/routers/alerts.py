import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import DbSession
from app.middleware.auth import CurrentUser
from app.middleware.ratelimit import rate_limit
from app.models import Alert
from app.schemas.alerts import AlertAnalyzeRequest, AlertDetail, AlertSummary
from app.services.alert_access import can_view_alert, scope_visible_alerts
from app.services.audit import log_audit
from app.services.explainer import explain
from app.services.language import resolve_language
from app.services.llm import LLMProviderError, LLMResponseError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertSummary])
def list_alerts(
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    origin: Literal["manual", "wazuh"] | None = Query(None),
    pending: bool | None = Query(
        None, description="true = only alerts without AI analysis yet"
    ),
) -> list[Alert]:
    stmt = select(Alert).order_by(Alert.created_at.desc()).offset(offset).limit(limit)
    # Analysts see their own alerts + the shared Wazuh queue; admins see all.
    stmt = scope_visible_alerts(stmt, user)
    if origin is not None:
        stmt = stmt.where(Alert.origin == origin)
    if pending is True:
        stmt = stmt.where(Alert.analyzed_at.is_(None))
    elif pending is False:
        stmt = stmt.where(Alert.analyzed_at.is_not(None))
    return list(db.scalars(stmt).all())


def _get_visible(db, user, alert_id: int) -> Alert:
    alert = db.get(Alert, alert_id, options=[selectinload(Alert.recommendations)])
    if alert is None or not can_view_alert(user, alert):
        # Don't reveal existence to users who can't see it.
        raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
    return alert


@router.get("/{alert_id}", response_model=AlertDetail)
def get_alert(alert_id: int, db: DbSession, user: CurrentUser) -> Alert:
    return _get_visible(db, user, alert_id)


@router.post(
    "/{alert_id}/analyze",
    response_model=AlertDetail,
    dependencies=[Depends(rate_limit)],
)
def analyze_alert(
    alert_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    payload: AlertAnalyzeRequest | None = None,
) -> Alert:
    """Run the Alert Explainer on an already-stored alert (e.g. from Wazuh).

    Overwrites summary / risk / MITRE / reasoning with the AI result and
    assigns the alert to the analyst who triaged it.
    """
    alert = _get_visible(db, user, alert_id)
    model = payload.model if payload else None
    language = resolve_language(payload.language if payload else None, request)
    try:
        result = explain(
            alert.log, alert.source, model=model, user=user, db=db, language=language
        )
    except LLMProviderError:
        logger.exception("LLM provider error in /alerts/{id}/analyze")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="AI provider error"
        ) from None
    except (LLMResponseError, ValidationError):
        logger.exception("LLM response could not be processed in /alerts/analyze")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI response could not be processed",
        ) from None

    alert.summary = result.summary
    alert.risk_level = result.risk_level
    # Keep Wazuh's own MITRE mapping if the model returns none.
    alert.mitre_techniques = result.mitre_techniques or alert.mitre_techniques
    alert.reasoning = result.reasoning
    alert.analyzed_at = datetime.now(UTC)
    if alert.user_id is None:
        alert.user_id = user.id
    log_audit(
        db,
        actor=user,
        action="alert.analyze",
        target_type="alert",
        target_id=alert.id,
        details={"origin": alert.origin, "risk_level": alert.risk_level},
    )
    db.commit()
    db.refresh(alert)
    return alert
