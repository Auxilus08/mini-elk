"""Shared schemas used by emitting services.

The collector keeps its own copy under collector/core/schemas.py so the two
sides stay decoupled at the wire level (JSON), not at the import level.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


LOG_LEVELS = ("debug", "info", "warn", "error", "critical")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def new_trace_id() -> str:
    return uuid.uuid4().hex


@dataclass
class LogEvent:
    timestamp: str
    service: str
    level: str
    message: str
    trace_id: str
    duration_ms: Optional[float] = None
    http_method: Optional[str] = None
    http_status: Optional[int] = None
    http_path: Optional[str] = None
    host: str = "localhost"

    def to_dict(self) -> Dict[str, Any]:
        # Drop None fields so ES doesn't see explicit nulls and the JSON is tight.
        return {k: v for k, v in asdict(self).items() if v is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def make(
        cls,
        service: str,
        level: str,
        message: str,
        *,
        trace_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
        http_method: Optional[str] = None,
        http_status: Optional[int] = None,
        http_path: Optional[str] = None,
        host: str = "localhost",
    ) -> "LogEvent":
        if level not in LOG_LEVELS:
            raise ValueError(f"invalid level {level!r}; expected one of {LOG_LEVELS}")
        return cls(
            timestamp=utc_now_iso(),
            service=service,
            level=level,
            message=message,
            trace_id=trace_id or new_trace_id(),
            duration_ms=duration_ms,
            http_method=http_method,
            http_status=http_status,
            http_path=http_path,
            host=host,
        )


@dataclass
class ServiceProfile:
    """Static simulation parameters for one service, loaded from sim_profiles.yaml."""

    service: str
    baseline_error_rate: float
    spike_error_rate: float
    spike_duration_s: int
    traffic_rps: int
    latency_baseline_ms: float
    latency_spike_ms: float
    silence_duration_s: Optional[int] = None

    @classmethod
    def from_yaml_entry(cls, service: str, entry: Dict[str, Any]) -> "ServiceProfile":
        return cls(
            service=service,
            baseline_error_rate=float(entry["baseline_error_rate"]),
            spike_error_rate=float(entry["spike_error_rate"]),
            spike_duration_s=int(entry["spike_duration_s"]),
            traffic_rps=int(entry["traffic_rps"]),
            latency_baseline_ms=float(entry["latency_baseline_ms"]),
            latency_spike_ms=float(entry["latency_spike_ms"]),
            silence_duration_s=(
                int(entry["silence_duration_s"])
                if "silence_duration_s" in entry
                else None
            ),
        )


@dataclass
class ScenarioState:
    """Mutable runtime scenario, written by the load generator and read by services."""

    name: str = "normal"
    target_service: Optional[str] = None
    inject: Optional[str] = None
    rps_multiplier: float = 1.0
    started_at: str = field(default_factory=utc_now_iso)
    duration_s: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScenarioState":
        return cls(
            name=data.get("name", "normal"),
            target_service=data.get("target_service"),
            inject=data.get("inject"),
            rps_multiplier=float(data.get("rps_multiplier", 1.0)),
            started_at=data.get("started_at", utc_now_iso()),
            duration_s=data.get("duration_s"),
        )
