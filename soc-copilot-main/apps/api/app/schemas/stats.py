"""Pydantic schemas for the analytics dashboard endpoint."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class StatsTotals(BaseModel):
    alerts: int
    recommendations: int
    users: int | None = None  # admin-only


class RiskBucket(BaseModel):
    risk_level: str
    count: int


class MitreBucket(BaseModel):
    technique: str
    count: int


class DailyPoint(BaseModel):
    day: date
    count: int


class UserBucket(BaseModel):
    user_id: int
    email: str
    alerts: int


class StatsResponse(BaseModel):
    scope: str  # "self" for analysts, "all" for admin
    totals: StatsTotals
    by_risk: list[RiskBucket]
    top_mitre: list[MitreBucket]
    daily_last_30d: list[DailyPoint]
    by_user: list[UserBucket] | None = None  # admin-only
