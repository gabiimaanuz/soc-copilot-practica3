"""Who can see / act on which alert.

Single source of truth used by the alerts, recommend and report routers.

* admin   → every alert.
* analyst → their own alerts **plus** the shared SIEM triage queue
  (alerts ingested from Wazuh). Once an analyst runs the AI analysis on a
  SIEM alert they become its owner (``user_id``), but it stays visible to
  the rest of the team because ``origin`` is still ``wazuh``.
* Legacy ownerless manual alerts (pre-auth) stay admin-only.
"""
from __future__ import annotations

from sqlalchemy import or_

from app.models import Alert, AlertOrigin, User, UserRole


def can_view_alert(user: User, alert: Alert) -> bool:
    if user.role == UserRole.ADMIN:
        return True
    if alert.user_id == user.id:
        return True
    return alert.origin == AlertOrigin.WAZUH.value


def scope_visible_alerts(stmt, user: User):
    if user.role == UserRole.ADMIN:
        return stmt
    return stmt.where(
        or_(Alert.user_id == user.id, Alert.origin == AlertOrigin.WAZUH.value)
    )
