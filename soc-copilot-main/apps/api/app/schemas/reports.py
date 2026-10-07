"""Schemas for the incident report generator (Práctica 2 — roadmap #4)."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.alerts import ChatMessage, ResponseLanguage, _validate_model_allowlist

_MITRE_RE = re.compile(r"^T\d{4}(\.\d{3})?$")


class IncidentReportRequest(BaseModel):
    alert_id: int | None = Field(None, ge=1)
    messages: list[ChatMessage] = Field(default_factory=list, max_length=60)
    log_context: str | None = Field(None, max_length=20_000)
    title: str | None = Field(None, max_length=200)
    analyst_notes: str | None = Field(None, max_length=4_000)
    include_transcript: bool = True
    model: str | None = None
    language: ResponseLanguage | None = None

    @field_validator("model")
    @classmethod
    def _model_in_allowlist(cls, v: str | None) -> str | None:
        return _validate_model_allowlist(v)

    @model_validator(mode="after")
    def _needs_material(self) -> IncidentReportRequest:
        has_log = bool(self.log_context and self.log_context.strip())
        if self.alert_id is None and not self.messages and not has_log:
            raise ValueError("provide alert_id, chat messages or log_context")
        return self


class TimelineEntry(BaseModel):
    time: str
    event: str


class IOC(BaseModel):
    type: str
    value: str
    context: str = ""


class IncidentReport(BaseModel):
    title: str
    severity: Literal["low", "medium", "high", "critical"]
    status: Literal["open", "contained", "resolved", "false_positive"]
    executive_summary: str
    timeline: list[TimelineEntry] = []
    affected_assets: list[str] = []
    iocs: list[IOC] = []
    mitre_techniques: list[str] = []
    analysis: str = ""
    actions_taken: list[str] = []
    recommendations: list[str] = []
    lessons_learned: str = ""
    conclusion: str = ""

    @field_validator("mitre_techniques")
    @classmethod
    def _clean_mitre(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for t in v:
            t = t.strip().upper()
            if _MITRE_RE.match(t) and t not in out:
                out.append(t)
        return out
