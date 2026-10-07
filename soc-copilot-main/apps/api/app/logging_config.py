"""Structured logging setup.

Production (`APP_ENV=production`): every record is serialised to a single
JSON line on stdout so it's queryable with ``jq`` or ingestable by Loki.
Development: human-readable ``levelname  logger: message`` lines.

Usage:
    from app.logging_config import configure_logging
    configure_logging()
    logger.info("auth.login", extra={"user_id": 1, "success": True})

The first positional argument (``msg``) is treated as the canonical
``event`` name. Anything passed via ``extra=`` lands as a top-level field
in the JSON payload.

Stdlib only — no extra dependencies.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from logging.config import dictConfig

# logging.LogRecord attributes we never want to echo into the JSON payload
# (they're either redundant or implementation details).
_RESERVED_RECORD_ATTRS = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "taskName", "asctime", "message",
    }
)


class JsonFormatter(logging.Formatter):
    """Render each LogRecord as a one-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRS or key.startswith("_"):
                continue
            try:
                json.dumps(value, default=str)
            except (TypeError, ValueError):
                value = repr(value)
            payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


def _is_production() -> bool:
    return os.environ.get("APP_ENV", "development").lower() in {"prod", "production"}


def configure_logging(force: bool = False) -> None:
    """Configure root logging once. Idempotent."""
    if not force and getattr(configure_logging, "_done", False):
        return

    formatter = "json" if _is_production() else "dev"
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {"()": "app.logging_config.JsonFormatter"},
                "dev": {
                    "format": "%(levelname)-8s %(name)s: %(message)s",
                },
            },
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "stream": sys.stdout,
                    "formatter": formatter,
                },
            },
            "loggers": {
                "app": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
            },
            "root": {"handlers": ["stdout"], "level": "WARNING"},
        }
    )
    configure_logging._done = True  # type: ignore[attr-defined]
