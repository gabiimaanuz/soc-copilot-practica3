"""Wazuh SIEM integration (Práctica 2 — roadmap #1).

Two ingestion paths feed the same function, :func:`ingest_alerts`:

* **Push** — Wazuh ``integratord`` runs ``custom-soccopilot.py`` for every
  alert above a level and POSTs the JSON to
  ``/api/integrations/wazuh/webhook`` (see ``integrations/wazuh/``).
* **Pull** — :func:`pull_from_indexer` queries the Wazuh Indexer
  (OpenSearch) ``wazuh-alerts-*`` index for documents newer than a cursor
  stored in ``app_settings``. Triggered manually by an admin or by the
  optional background poller started in ``main.lifespan``.

Both paths are idempotent: alerts are deduplicated on
``(origin='wazuh', external_id=<wazuh alert id>)``.

Ingestion does NOT call the LLM. Alerts land in a shared triage queue
pre-filled with what Wazuh already knows (rule description, MITRE ids,
risk derived from rule.level). An analyst clicks "Analizar con IA" to run
the Alert Explainer on demand — this keeps the shared Gemini quota safe
from an alert storm.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import Alert, AlertOrigin, AppSetting

logger = logging.getLogger(__name__)

PULL_CURSOR_KEY = "wazuh_pull_cursor"
PULL_LAST_RUN_KEY = "wazuh_pull_last_run"
PULL_LAST_ERROR_KEY = "wazuh_pull_last_error"
PUSH_LAST_RECEIVED_KEY = "wazuh_push_last_received"

# Max length of the log stored per alert (matches ExplainRequest.max_length
# so the Alert Explainer can always re-analyse it).
MAX_LOG_CHARS = 20_000
_MITRE_RE = re.compile(r"^T\d{4}(\.\d{3})?$")


# ─── Normalisation (pure, unit-testable) ────────────────────────────────


def level_to_risk(level: int | None) -> str | None:
    """Map Wazuh rule.level (0-15) to the app's risk scale.

    Based on Wazuh's own rule classification table:
    0-6 low/informational, 7-9 medium, 10-12 high, 13-15 critical.
    """
    if level is None:
        return None
    if level >= 13:
        return "critical"
    if level >= 10:
        return "high"
    if level >= 7:
        return "medium"
    return "low"


def _parse_ts(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    # Wazuh uses "2026-10-05T10:11:12.345+0000" (no colon in offset).
    m = re.match(r"^(.*[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)([+-]\d{2})(\d{2})$", v)
    if m:
        v = f"{m.group(1)}{m.group(2)}:{m.group(3)}"
    v = v.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _external_id(alert: dict[str, Any]) -> str:
    """Wazuh alert id, or a stable content hash when absent."""
    raw = alert.get("id") or alert.get("_id")
    if raw:
        return str(raw)[:128]
    digest = hashlib.sha256(
        json.dumps(alert, sort_keys=True, default=str).encode()
    ).hexdigest()
    return f"sha256:{digest[:64]}"


@dataclass
class NormalizedAlert:
    external_id: str
    log: str
    source: str
    summary: str | None
    risk_level: str | None
    mitre_techniques: list[str]
    rule_level: int | None
    agent_name: str | None
    event_at: datetime | None


def normalize_wazuh_alert(alert: dict[str, Any]) -> NormalizedAlert:
    """Turn a raw Wazuh alert (alerts.json format) into our Alert fields."""
    if not isinstance(alert, dict):
        raise ValueError("wazuh alert must be a JSON object")

    rule = alert.get("rule") or {}
    agent = alert.get("agent") or {}
    decoder = alert.get("decoder") or {}
    mitre = (rule.get("mitre") or {}) if isinstance(rule, dict) else {}

    level = _as_int(rule.get("level")) if isinstance(rule, dict) else None
    description = rule.get("description") if isinstance(rule, dict) else None
    agent_name = agent.get("name") if isinstance(agent, dict) else None
    decoder_name = decoder.get("name") if isinstance(decoder, dict) else None

    raw_ids = mitre.get("id") if isinstance(mitre, dict) else None
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    techniques = [
        t for t in (str(x).strip().upper() for x in (raw_ids or [])) if _MITRE_RE.match(t)
    ][:20]

    source_parts = ["wazuh"]
    if agent_name:
        source_parts.append(str(agent_name))
    if decoder_name:
        source_parts.append(str(decoder_name))
    source = ":".join(source_parts)[:200]

    # The stored "log" is what the Alert Explainer will read. A short
    # human header + the full JSON gives the LLM all the context Wazuh has.
    header_lines = [
        f"[Wazuh] rule {rule.get('id', '?')} level {level if level is not None else '?'}: "
        f"{description or 'sin descripción'}",
    ]
    if agent_name:
        header_lines.append(
            f"agent: {agent_name} ({agent.get('ip', 'n/a')}) id={agent.get('id', 'n/a')}"
        )
    if alert.get("location"):
        header_lines.append(f"location: {alert.get('location')}")
    if alert.get("full_log"):
        header_lines.append(f"full_log: {alert.get('full_log')}")
    body = json.dumps(alert, ensure_ascii=False, default=str, indent=1)
    log = "\n".join(header_lines) + "\n\nraw_alert:\n" + body
    if len(log) > MAX_LOG_CHARS:
        log = log[: MAX_LOG_CHARS - 20] + "\n…[truncado]"

    return NormalizedAlert(
        external_id=_external_id(alert),
        log=log,
        source=source,
        summary=(str(description)[:2000] if description else None),
        risk_level=level_to_risk(level),
        mitre_techniques=techniques,
        rule_level=level,
        agent_name=(str(agent_name)[:255] if agent_name else None),
        event_at=_parse_ts(alert.get("timestamp") or alert.get("@timestamp")),
    )


# ─── Ingestion (DB) ─────────────────────────────────────────────────────


@dataclass
class IngestResult:
    received: int = 0
    created: int = 0
    duplicates: int = 0
    below_threshold: int = 0
    invalid: int = 0
    created_ids: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "received": self.received,
            "created": self.created,
            "duplicates": self.duplicates,
            "below_threshold": self.below_threshold,
            "invalid": self.invalid,
            "created_ids": self.created_ids,
        }


def ingest_alerts(
    db: Session,
    alerts: list[dict[str, Any]],
    *,
    min_level: int | None = None,
) -> IngestResult:
    """Store Wazuh alerts, skipping duplicates and low-level noise.

    Commits per alert so a single bad row (or a race with a concurrent
    push/pull of the same alert) never rolls back the whole batch.
    """
    threshold = get_settings().wazuh_min_rule_level if min_level is None else min_level
    result = IngestResult(received=len(alerts))

    for raw in alerts:
        try:
            n = normalize_wazuh_alert(raw)
        except ValueError:
            result.invalid += 1
            continue

        if n.rule_level is not None and n.rule_level < threshold:
            result.below_threshold += 1
            continue

        exists = db.scalar(
            select(Alert.id).where(
                Alert.origin == AlertOrigin.WAZUH.value,
                Alert.external_id == n.external_id,
            )
        )
        if exists is not None:
            result.duplicates += 1
            continue

        row = Alert(
            origin=AlertOrigin.WAZUH.value,
            external_id=n.external_id,
            log=n.log,
            source=n.source,
            summary=n.summary,
            risk_level=n.risk_level,
            mitre_techniques=n.mitre_techniques or None,
            rule_level=n.rule_level,
            agent_name=n.agent_name,
            event_at=n.event_at,
            user_id=None,  # shared triage queue until an analyst claims it
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            # Same alert inserted concurrently by the other ingestion path.
            db.rollback()
            result.duplicates += 1
            continue
        result.created += 1
        result.created_ids.append(row.id)

    if result.created:
        logger.info("wazuh.ingest", extra=result.as_dict())
    return result


# ─── Small key/value helpers on app_settings ────────────────────────────


def _get_setting(db: Session, key: str) -> str | None:
    row = db.get(AppSetting, key)
    return row.value if row else None


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value[:1024]))
    else:
        row.value = value[:1024]
        row.updated_at = datetime.now(UTC)
    db.commit()


def mark_push_received(db: Session) -> None:
    _set_setting(db, PUSH_LAST_RECEIVED_KEY, datetime.now(UTC).isoformat())


# ─── Pull from the Wazuh Indexer ────────────────────────────────────────


class WazuhPullError(RuntimeError):
    """Indexer unreachable, auth failed or returned an unexpected payload."""


def build_indexer_query(since: str, min_level: int, size: int) -> dict[str, Any]:
    """OpenSearch query for alerts at/after ``since`` above ``min_level``.

    ``gte`` (not ``gt``) so alerts sharing the cursor's exact timestamp are
    never skipped; the re-fetched ones are dropped by deduplication.
    """
    return {
        "size": size,
        "sort": [{"timestamp": {"order": "asc"}}],
        "query": {
            "bool": {
                "filter": [
                    {"range": {"timestamp": {"gte": since}}},
                    {"range": {"rule.level": {"gte": min_level}}},
                ]
            }
        },
    }


def _tls_verify(settings: Settings) -> bool | str:
    if settings.wazuh_indexer_ca_cert:
        return settings.wazuh_indexer_ca_cert
    return settings.wazuh_indexer_verify_tls


def fetch_indexer_alerts(
    settings: Settings, since: str
) -> list[dict[str, Any]]:
    """Run the search against the indexer and return ``_source`` docs."""
    import httpx

    url = (
        settings.wazuh_indexer_url.rstrip("/")
        + "/"
        + settings.wazuh_indexer_index.strip("/")
        + "/_search"
    )
    body = build_indexer_query(
        since, settings.wazuh_min_rule_level, settings.wazuh_pull_batch_size
    )
    auth = (
        (settings.wazuh_indexer_user, settings.wazuh_indexer_password)
        if settings.wazuh_indexer_user
        else None
    )
    try:
        with httpx.Client(
            verify=_tls_verify(settings),
            timeout=settings.wazuh_indexer_timeout_seconds,
        ) as client:
            resp = client.post(url, json=body, auth=auth)
    except httpx.HTTPError as exc:
        raise WazuhPullError(f"indexer unreachable: {exc.__class__.__name__}") from exc

    if resp.status_code in (401, 403):
        raise WazuhPullError(f"indexer auth failed ({resp.status_code})")
    if resp.status_code >= 400:
        raise WazuhPullError(f"indexer error {resp.status_code}")
    try:
        hits = resp.json()["hits"]["hits"]
    except (ValueError, KeyError, TypeError) as exc:
        raise WazuhPullError("unexpected indexer response") from exc

    docs: list[dict[str, Any]] = []
    for h in hits:
        src = h.get("_source")
        if isinstance(src, dict):
            # Prefer the Wazuh alert id; fall back to the OpenSearch doc id.
            src.setdefault("id", h.get("_id"))
            docs.append(src)
    return docs


def pull_from_indexer(db: Session) -> dict[str, Any]:
    """One pull cycle: fetch since cursor → ingest → advance cursor."""
    settings = get_settings()
    if not settings.wazuh_pull_enabled:
        raise WazuhPullError("pull mode not configured (WAZUH_INDEXER_URL)")

    since = _get_setting(db, PULL_CURSOR_KEY)
    if not since:
        since = (
            datetime.now(UTC)
            - timedelta(minutes=settings.wazuh_pull_initial_lookback_minutes)
        ).isoformat()

    try:
        docs = fetch_indexer_alerts(settings, since)
    except WazuhPullError as exc:
        _set_setting(db, PULL_LAST_ERROR_KEY, str(exc))
        _set_setting(db, PULL_LAST_RUN_KEY, datetime.now(UTC).isoformat())
        raise

    result = ingest_alerts(db, docs)

    # Advance the cursor to the newest timestamp seen. Stored as ISO-8601
    # with a colon offset ("+00:00"), which OpenSearch's
    # strict_date_optional_time parser accepts (Wazuh's raw "+0000" form
    # is not guaranteed to be).
    newest_dt = _parse_ts(since)
    for d in docs:
        ts = _parse_ts(d.get("timestamp"))
        if ts and (newest_dt is None or ts > newest_dt):
            newest_dt = ts
    newest = newest_dt.isoformat() if newest_dt else since
    _set_setting(db, PULL_CURSOR_KEY, newest)
    _set_setting(db, PULL_LAST_RUN_KEY, datetime.now(UTC).isoformat())
    _set_setting(db, PULL_LAST_ERROR_KEY, "")

    out = result.as_dict()
    out["cursor"] = newest
    out["fetched"] = len(docs)
    return out


def integration_status(db: Session) -> dict[str, Any]:
    settings = get_settings()
    since_24h = datetime.now(UTC) - timedelta(hours=24)
    total = db.scalar(
        select(func.count(Alert.id)).where(Alert.origin == AlertOrigin.WAZUH.value)
    ) or 0
    last_24h = db.scalar(
        select(func.count(Alert.id)).where(
            Alert.origin == AlertOrigin.WAZUH.value, Alert.created_at >= since_24h
        )
    ) or 0
    pending = db.scalar(
        select(func.count(Alert.id)).where(
            Alert.origin == AlertOrigin.WAZUH.value, Alert.analyzed_at.is_(None)
        )
    ) or 0
    return {
        "push_enabled": settings.wazuh_push_enabled,
        "pull_enabled": settings.wazuh_pull_enabled,
        "poll_interval_seconds": settings.wazuh_poll_interval_seconds,
        "min_rule_level": settings.wazuh_min_rule_level,
        "indexer_url": settings.wazuh_indexer_url or None,
        "push_last_received": _get_setting(db, PUSH_LAST_RECEIVED_KEY),
        "pull_last_run": _get_setting(db, PULL_LAST_RUN_KEY),
        "pull_last_error": _get_setting(db, PULL_LAST_ERROR_KEY) or None,
        "pull_cursor": _get_setting(db, PULL_CURSOR_KEY),
        "alerts_total": total,
        "alerts_last_24h": last_24h,
        "alerts_pending": pending,
    }


# ─── Background poller ──────────────────────────────────────────────────


async def poll_forever(session_factory) -> None:
    """Pull every WAZUH_POLL_INTERVAL_SECONDS until cancelled.

    Runs the blocking pull in a worker thread so the event loop stays
    responsive. Errors are logged and stored in app_settings, never raised.
    """
    interval = max(15, get_settings().wazuh_poll_interval_seconds)
    logger.info("wazuh.poller.start", extra={"interval_s": interval})

    def _once() -> None:
        db = session_factory()
        try:
            pull_from_indexer(db)
        except WazuhPullError as exc:
            logger.warning("wazuh.poller.error", extra={"error": str(exc)})
        except Exception:  # poller must never die
            logger.exception("wazuh.poller.crash")
        finally:
            db.close()

    while True:
        await asyncio.to_thread(_once)
        await asyncio.sleep(interval)
