"""Incident report endpoint (Práctica 2 — roadmap #4).

POST /api/reports/incident            → application/pdf (download)
POST /api/reports/incident?format=json → structured report (preview/tests)
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy.orm import selectinload

from app.db import DbSession
from app.middleware.auth import CurrentUser
from app.middleware.ratelimit import rate_limit
from app.models import Alert
from app.schemas.reports import IncidentReport, IncidentReportRequest
from app.services.alert_access import can_view_alert
from app.services.audit import log_audit
from app.services.incident_report import ReportMeta, build_report, render_pdf
from app.services.language import resolve_language
from app.services.llm import LLMProviderError, LLMResponseError

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/reports", tags=["incident-report"], dependencies=[Depends(rate_limit)]
)


@router.post("/incident", response_model=None)
def incident_report(
    payload: IncidentReportRequest,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    fmt: Literal["pdf", "json"] = Query("pdf", alias="format"),
) -> Response | IncidentReport:
    alert: Alert | None = None
    if payload.alert_id is not None:
        alert = db.get(
            Alert, payload.alert_id, options=[selectinload(Alert.recommendations)]
        )
        if alert is None or not can_view_alert(user, alert):
            raise HTTPException(status_code=404, detail=f"alert {payload.alert_id} not found")

    # Language: the analyst's own words in the chat decide; else UI language.
    analyst_text = " ".join(m.content for m in payload.messages if m.role == "user")
    language = resolve_language(
        payload.language, request, text=analyst_text or payload.analyst_notes
    )

    try:
        report = build_report(
            alert=alert,
            messages=payload.messages,
            log_context=payload.log_context,
            analyst_notes=payload.analyst_notes,
            title_hint=payload.title,
            language=language,
            model=payload.model,
            user=user,
            db=db,
        )
    except LLMProviderError:
        logger.exception("LLM provider error in /reports/incident")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="AI provider error"
        ) from None
    except (LLMResponseError, ValidationError):
        logger.exception("LLM response could not be processed in /reports/incident")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI response could not be processed",
        ) from None

    now = datetime.now(UTC)
    reference = f"INC-{now:%Y%m%d}-" + (f"A{alert.id}" if alert else f"U{user.id}-{now:%H%M%S}")

    log_audit(
        db,
        actor=user,
        action="report.incident",
        target_type="alert" if alert else None,
        target_id=alert.id if alert else None,
        target_label=reference,
        details={
            "format": fmt,
            "severity": report.severity,
            "status": report.status,
            "language": language,
            "chat_messages": len(payload.messages),
        },
    )
    db.commit()

    if fmt == "json":
        return report

    full_name = " ".join(p for p in (user.name, user.last_name) if p) or user.email
    pdf = render_pdf(
        report,
        ReportMeta(
            reference=reference,
            analyst=f"{full_name} <{user.email}>",
            language=language,
            alert=alert,
            messages=payload.messages,
            analyst_notes=payload.analyst_notes,
            include_transcript=payload.include_transcript,
            generated_at=now,
        ),
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{reference}.pdf"',
            "Cache-Control": "no-store",
        },
    )
