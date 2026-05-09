"""Error-rate spike detector — Phase 1 primary."""

from __future__ import annotations

import logging
from typing import Optional

from collector.core.schemas import (
    AnomalyEvent,
    BucketAccumulator,
    LogEvent,
    ServiceWindowState,
    iso,
    utcnow,
)
from .base import Detector


log = logging.getLogger(__name__)


class ErrorRateSpikeDetector(Detector):
    name = "error_rate_spike"

    def evaluate(
        self,
        event: Optional[LogEvent],
        state: ServiceWindowState,
        flushed_bucket: Optional[BucketAccumulator],
    ) -> Optional[AnomalyEvent]:
        if flushed_bucket is None:
            return None

        bucket = flushed_bucket
        if bucket.request_count < state.min_requests_per_bucket:
            return None
        if len(state.history) < 3:
            return None

        mean, stddev = state.baseline_stats()
        if stddev == 0:
            return None

        z = (bucket.error_rate - mean) / stddev
        if z < state.z_score_threshold:
            return None
        if state.should_suppress():
            return None

        severity = "critical" if z > 6.0 else "warning"
        anomaly = AnomalyEvent(
            timestamp=iso(utcnow()),
            anomaly_type="error_rate_spike",
            service=state.service,
            severity=severity,
            z_score=round(z, 4),
            current_value=round(bucket.error_rate, 6),
            baseline_mean=round(mean, 6),
            baseline_stddev=round(stddev, 6),
            window_seconds=state.bucket_duration_s,
            sample_count=bucket.request_count,
            threshold_used=state.z_score_threshold,
            sampled_trace_ids=list(bucket.sampled_trace_ids),
        )
        state.record_anomaly()
        return anomaly
