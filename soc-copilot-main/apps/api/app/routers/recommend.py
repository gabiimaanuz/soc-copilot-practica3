import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from app.db import DbSession
from app.middleware.auth import CurrentUser
from app.middleware.ratelimit import rate_limit
from app.models import Alert, Recommendation
from app.schemas.alerts import RecommendRequest, RecommendResponse
from app.services.alert_access import can_view_alert
from app.services.audit import log_audit
from app.services.language import resolve_language
from app.services.llm import LLMProviderError, LLMResponseError
from app.services.recommender import recommend

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/recommend",
    tags=["next-step-recommender"],
    dependencies=[Depends(rate_limit)],
)


@router.post("", response_model=RecommendResponse)
def recommend_actions(
    payload: RecommendRequest, db: DbSession, user: CurrentUser, request: Request
) -> RecommendResponse:
    alert: Alert | None = None
    log = payload.log
    source = payload.source
    explanation: str | None = None
    risk_level: str | None = None

    if payload.alert_id is not None:
        alert = db.get(Alert, payload.alert_id)
        if alert is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"alert {payload.alert_id} not found",
            )
        # Ownership: analysts act on their own alerts + the shared SIEM
        # queue; admin sees all (see services/alert_access.py).
        if not can_view_alert(user, alert):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"alert {payload.alert_id} not found",
            )
        log = alert.log
        source = alert.source
        explanation = alert.summary
        risk_level = alert.risk_level

    # Schema-level validators already enforce log non-empty when alert_id is
    # absent; this guard is belt-and-suspenders.
    if not log or not log.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="provide either alert_id of an existing alert or non-empty log",
        )

    try:
        result = recommend(
            log,
            source,
            explanation,
            risk_level,
            model=payload.model,
            user=user,
            db=db,
            language=resolve_language(payload.language, request),
        )
    except LLMProviderError:
        logger.exception("LLM provider error in /recommend")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="AI provider error"
        ) from None
    except (LLMResponseError, ValidationError):
        logger.exception("LLM response could not be processed in /recommend")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI response could not be processed",
        ) from None

    if alert is not None:
        rec = Recommendation(
            alert_id=alert.id,
            actions=[a.model_dump() for a in result.actions],
            priority=result.priority,
            learning_notes=result.learning_notes,
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        result.id = rec.id
        result.alert_id = alert.id

    log_audit(
        db,
        actor=user,
        action="recommend.actions",
        target_type="alert" if alert else None,
        target_id=alert.id if alert else None,
    )
    db.commit()

    return result
