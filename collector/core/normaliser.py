"""Validate, enrich, and reject malformed Kafka payloads."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .schemas import LogEvent, VALID_LEVELS, iso


log = logging.getLogger(__name__)

REQUIRED_FIELDS = ("service", "level", "message")
LEVEL_ALIASES = {"warning": "warn"}


def _coerce_timestamp(raw: Any) -> Optional[str]:
    if not isinstance(raw, str) or not raw:
        return None
    candidate = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return iso(dt)


def parse(raw: bytes | str | Dict[str, Any]) -> Optional[LogEvent]:
    """Decode → validate → normalise. Returns ``None`` on rejection."""
    if isinstance(raw, (bytes, bytearray)):
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            log.warning("normaliser: json decode failed: %s", exc)
            return None
    elif isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("normaliser: json decode failed: %s", exc)
            return None
    else:
        data = raw

    if not isinstance(data, dict):
        log.warning("normaliser: payload is not an object: %r", type(data).__name__)
        return None

    for f in REQUIRED_FIELDS:
        if f not in data or data[f] in (None, ""):
            log.warning("normaliser: missing required field %r in %r", f, data)
            return None

    ts_raw = data.get("@timestamp") or data.get("timestamp")
    timestamp = _coerce_timestamp(ts_raw)
    if timestamp is None:
        log.warning("normaliser: invalid or missing timestamp: %r", ts_raw)
        return None

    level = str(data["level"]).strip().lower()
    level = LEVEL_ALIASES.get(level, level)
    if level not in VALID_LEVELS:
        log.warning("normaliser: invalid level %r", data["level"])
        return None

    trace_id = data.get("trace_id") or uuid.uuid4().hex

    duration_ms = data.get("duration_ms")
    if duration_ms is not None:
        try:
            duration_ms = float(duration_ms)
        except (TypeError, ValueError):
            log.warning("normaliser: invalid duration_ms %r — dropping field", duration_ms)
            duration_ms = None

    http_status = data.get("http_status")
    if http_status is not None:
        try:
            http_status = int(http_status)
        except (TypeError, ValueError):
            http_status = None

    return LogEvent(
        timestamp=timestamp,
        service=str(data["service"]),
        level=level,
        message=str(data["message"]),
        trace_id=str(trace_id),
        duration_ms=duration_ms,
        http_method=data.get("http_method"),
        http_status=http_status,
        http_path=data.get("http_path"),
        host=str(data.get("host", "localhost")),
    )
