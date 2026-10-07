from fastapi import APIRouter

from app.db import DbSession
from app.middleware.auth import CurrentUser
from app.schemas.stats import StatsResponse
from app.services.stats import compute_stats

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("", response_model=StatsResponse)
def get_stats(db: DbSession, user: CurrentUser) -> StatsResponse:
    """Aggregated metrics for the dashboard.

    Analysts see only their own alerts; admins see everything plus a
    per-user breakdown and total user count.
    """
    return compute_stats(db, user)
