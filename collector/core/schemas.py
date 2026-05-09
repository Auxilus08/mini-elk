"""Collector-side schemas.

A LogEvent is duplicated here (rather than imported from services/shared) so the
collector and the emitting services are coupled at the wire format only.
"""

from __future__ import annotations

import math
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple


VALID_LEVELS = ("debug", "info", "warn", "error", "critical")
ERROR_LEVELS = ("error", "critical")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


@dataclass
class LogEvent:
    """Wire-format mirror of services/shared/schemas.py:LogEvent."""

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

    def to_es_doc(self) -> Dict[str, Any]:
        # Rename `timestamp` → `@timestamp` for ES, drop None fields.
        out: Dict[str, Any] = {"@timestamp": self.timestamp}
        for k, v in asdict(self).items():
            if k == "timestamp" or v is None:
                continue
            out[k] = v
        return out

    @property
    def is_error(self) -> bool:
        if self.level in ERROR_LEVELS:
            return True
        if self.http_status is not None and self.http_status >= 500:
            return True
        return False


@dataclass
class BucketAccumulator:
    start: datetime
    request_count: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0
    latency_sample_count: int = 0
    sampled_trace_ids: List[str] = field(default_factory=list)
    max_trace_samples: int = 20

    @property
    def error_rate(self) -> float:
        if self.request_count == 0:
            return 0.0
        return self.error_count / self.request_count

    @property
    def avg_latency_ms(self) -> float:
        if self.latency_sample_count == 0:
            return 0.0
        return self.total_latency_ms / self.latency_sample_count

    @property
    def latency_coverage(self) -> float:
        if self.request_count == 0:
            return 0.0
        return self.latency_sample_count / self.request_count

    def add(self, event: LogEvent) -> None:
        self.request_count += 1
        if event.is_error:
            self.error_count += 1
            # Bias trace sampling toward errors — they are what drill-down needs.
            if len(self.sampled_trace_ids) < self.max_trace_samples:
                self.sampled_trace_ids.append(event.trace_id)
        elif len(self.sampled_trace_ids) < self.max_trace_samples // 2:
            self.sampled_trace_ids.append(event.trace_id)
        if event.duration_ms is not None:
            self.total_latency_ms += float(event.duration_ms)
            self.latency_sample_count += 1


def _aligned_bucket_start(ts: datetime, bucket_duration_s: int) -> datetime:
    """Floor ``ts`` to the most recent bucket boundary."""
    epoch = ts.timestamp()
    floored = (int(epoch) // bucket_duration_s) * bucket_duration_s
    return datetime.fromtimestamp(floored, tz=timezone.utc)


@dataclass
class ServiceWindowState:
    service: str
    bucket_duration_s: int = 60
    history_maxlen: int = 30
    min_requests_per_bucket: int = 10
    cooldown_s: int = 300
    z_score_threshold: float = 3.0

    current: BucketAccumulator = field(default=None)  # type: ignore[assignment]
    history: deque = field(default=None)  # type: ignore[assignment]
    last_anomaly_at: Optional[datetime] = None
    # Last bucket flushed by ingest()/tick() — detectors read this.
    last_flushed_bucket: Optional[BucketAccumulator] = None

    def __post_init__(self) -> None:
        if self.history is None:
            self.history = deque(maxlen=self.history_maxlen)
        if self.current is None:
            self.current = BucketAccumulator(start=_aligned_bucket_start(utcnow(), self.bucket_duration_s))

    # ------------------------------------------------------------------
    def _parse_event_ts(self, event: LogEvent) -> datetime:
        ts = event.timestamp.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return utcnow()

    def _advance_to(self, now: datetime) -> List[BucketAccumulator]:
        """Roll forward through bucket boundaries up to ``now``.

        Each crossed boundary flushes the current bucket to history. Empty
        zero-buckets are synthesised for gaps so silence detection has data to
        chew on. Returns every flushed bucket in chronological order so the
        detector registry can evaluate each one.
        """
        flushed: List[BucketAccumulator] = []
        if now < self.current.start + timedelta(seconds=self.bucket_duration_s):
            return flushed

        target_start = _aligned_bucket_start(now, self.bucket_duration_s)
        while self.current.start < target_start:
            self.history.append(self.current)
            flushed.append(self.current)
            next_start = self.current.start + timedelta(seconds=self.bucket_duration_s)
            self.current = BucketAccumulator(start=next_start)
        if flushed:
            self.last_flushed_bucket = flushed[-1]
        return flushed

    def ingest(self, event: LogEvent) -> List[BucketAccumulator]:
        """Add event to current bucket, advancing time if needed.

        Returns the list of buckets flushed by this call (often empty, sometimes
        one, occasionally several if the event arrives after a long quiet gap).
        """
        event_dt = self._parse_event_ts(event)
        flushed = self._advance_to(event_dt)
        # Late events older than the current bucket get dropped silently — they
        # would corrupt the per-bucket counts otherwise.
        if event_dt >= self.current.start:
            self.current.add(event)
        return flushed

    def tick(self, now: Optional[datetime] = None) -> List[BucketAccumulator]:
        """Advance the clock without an event. Used by the periodic scanner."""
        return self._advance_to(now or utcnow())

    # ------------------------------------------------------------------
    # Statistics over history
    # ------------------------------------------------------------------
    def _baseline_for(self, values: List[float]) -> Tuple[float, float]:
        if len(values) < 3:
            return 0.0, 0.0
        n = len(values)
        mean = sum(values) / n
        var = sum((v - mean) ** 2 for v in values) / n
        return mean, math.sqrt(var)

    def baseline_stats(self) -> Tuple[float, float]:
        """Mean and stddev of error_rate across history buckets."""
        return self._baseline_for([b.error_rate for b in self.history])

    def baseline_volume(self) -> Tuple[float, float]:
        return self._baseline_for([float(b.request_count) for b in self.history])

    def baseline_latency(self) -> Tuple[float, float]:
        # Only buckets that actually had latency samples count toward the baseline.
        samples = [b.avg_latency_ms for b in self.history if b.latency_sample_count > 0]
        return self._baseline_for(samples)

    def z_score(self, value: float, mean: Optional[float] = None, stddev: Optional[float] = None) -> Optional[float]:
        if mean is None or stddev is None:
            mean, stddev = self.baseline_stats()
        if stddev == 0:
            return None
        return (value - mean) / stddev

    def should_suppress(self, now: Optional[datetime] = None) -> bool:
        if self.last_anomaly_at is None:
            return False
        now = now or utcnow()
        return (now - self.last_anomaly_at).total_seconds() < self.cooldown_s

    def record_anomaly(self, when: Optional[datetime] = None) -> None:
        self.last_anomaly_at = when or utcnow()


@dataclass
class AnomalyEvent:
    timestamp: str
    anomaly_type: str
    service: str
    severity: str
    z_score: float
    current_value: float
    baseline_mean: float
    baseline_stddev: float
    window_seconds: int
    sample_count: int
    threshold_used: float
    sampled_trace_ids: List[str]
    resolved: bool = False
    # `id` is not in the brief but search-api needs a stable handle for
    # /anomalies/{id}/logs and /logs/anomaly-window/{anomaly_id}.
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Mirror logs-* convention so Kibana-style time queries Just Work.
        d["@timestamp"] = d.pop("timestamp")
        return d
