"""Verify the JSON log formatter."""
from __future__ import annotations

import io
import json
import logging

from app.logging_config import JsonFormatter


def _record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="auth.login",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formatter_emits_parseable_json_with_extras():
    formatter = JsonFormatter()
    record = _record(user_id=42, email="t@example.com", success=True, ip="1.2.3.4")

    line = formatter.format(record)
    payload = json.loads(line)

    assert payload["event"] == "auth.login"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["user_id"] == 42
    assert payload["email"] == "t@example.com"
    assert payload["success"] is True
    assert payload["ip"] == "1.2.3.4"
    assert "timestamp" in payload


def test_formatter_falls_back_to_repr_for_non_serializable_values():
    formatter = JsonFormatter()

    class Weird:
        def __repr__(self) -> str:
            return "<weird-obj>"

    record = _record(blob=Weird())
    payload = json.loads(formatter.format(record))
    assert payload["blob"] == "<weird-obj>"


def test_handler_pipeline_writes_json_line():
    """End-to-end: a logger using the formatter produces one JSON line."""
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(JsonFormatter())

    logger = logging.getLogger("app.test_logging_pipeline")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    logger.info("llm.call", extra={"user_id": 1, "byo": False, "latency_ms": 123})

    output = buffer.getvalue().strip()
    assert "\n" not in output
    payload = json.loads(output)
    assert payload["event"] == "llm.call"
    assert payload["latency_ms"] == 123
    assert payload["byo"] is False
