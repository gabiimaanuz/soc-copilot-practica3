"""Aggregations for the /api/stats dashboard endpoint.

All queries are scoped: analysts see only their own alerts (matching the
ownership rules in routers/alerts.py); admins see everything including
legacy ownerless rows. Recommendations are joined through Alert so the
same scope applies.

Postgres-only: relies on `unnest()` over `mitre_techniques ARRAY` and
`date_trunc('day', ...)`. SQLite can't run these, so the unit suite for
this service uses fakes and the HTTP path is covered by E2E only.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, func, literal, select
from sqlalchemy.orm import Session

from app.models import Alert, Recommendation, User, UserRole
from app.schemas.stats import (
    DailyPoint,
    MitreBucket,
    RiskBucket,
    StatsResponse,
    StatsTotals,
    UserBucket,
)


def _scope_alerts(stmt, user: User):
    if user.role != UserRole.ADMIN:
        return stmt.where(Alert.user_id == user.id)
    return stmt


def compute_stats(db: Session, user: User) -> StatsResponse:
    is_admin = user.role == UserRole.ADMIN
    cutoff = datetime.now(UTC) - timedelta(days=30)

    # ── Totals ──────────────────────────────────────────────────────────
    alerts_total = db.scalar(
        _scope_alerts(select(func.count(Alert.id)), user)
    ) or 0

    rec_q = select(func.count(Recommendation.id)).join(
        Alert, Recommendation.alert_id == Alert.id
    )
    rec_total = db.scalar(_scope_alerts(rec_q, user)) or 0

    users_total: int | None = None
    if is_admin:
        users_total = db.scalar(select(func.count(User.id))) or 0

    # ── By risk ─────────────────────────────────────────────────────────
    risk_label = func.coalesce(Alert.risk_level, literal("unknown"))
    risk_q = (
        select(risk_label.label("risk"), func.count(Alert.id).label("n"))
        .group_by(risk_label)
        .order_by(desc("n"))
    )
    by_risk = [
        RiskBucket(risk_level=row.risk, count=row.n)
        for row in db.execute(_scope_alerts(risk_q, user)).all()
    ]

    # ── Top MITRE ───────────────────────────────────────────────────────
    technique_col = func.unnest(Alert.mitre_techniques).label("technique")
    mitre_q = (
        select(technique_col, func.count().label("n"))
        .where(Alert.mitre_techniques.isnot(None))
        .group_by("technique")
        .order_by(desc("n"))
        .limit(10)
    )
    top_mitre = [
        MitreBucket(technique=row.technique, count=row.n)
        for row in db.execute(_scope_alerts(mitre_q, user)).all()
        if row.technique
    ]

    # ── Daily last 30 days ──────────────────────────────────────────────
    day_col = func.date_trunc("day", Alert.created_at).label("day")
    daily_q = (
        select(day_col, func.count(Alert.id).label("n"))
        .where(Alert.created_at >= cutoff)
        .group_by("day")
        .order_by("day")
    )
    daily = [
        DailyPoint(day=row.day.date(), count=row.n)
        for row in db.execute(_scope_alerts(daily_q, user)).all()
    ]

    # ── By user (admin only) ────────────────────────────────────────────
    by_user: list[UserBucket] | None = None
    if is_admin:
        per_user_q = (
            select(
                User.id,
                User.email,
                func.count(Alert.id).label("n"),
            )
            .join(Alert, Alert.user_id == User.id)
            .group_by(User.id, User.email)
            .order_by(desc("n"))
            .limit(20)
        )
        by_user = [
            UserBucket(user_id=row.id, email=row.email, alerts=row.n)
            for row in db.execute(per_user_q).all()
        ]

    return StatsResponse(
        scope="all" if is_admin else "self",
        totals=StatsTotals(
            alerts=int(alerts_total),
            recommendations=int(rec_total),
            users=users_total,
        ),
        by_risk=by_risk,
        top_mitre=top_mitre,
        daily_last_30d=daily,
        by_user=by_user,
    )
