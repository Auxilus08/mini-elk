"""Latency-spike detector.

Skips buckets where fewer than half of events carried ``duration_ms`` — the
average over a small sample is too noisy to baseline.
"""

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

MIN_LATENCY_COVERAGE = 0.5


class LatencySpikeDetector(Detector):
    name = "latency_spike"

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
        if bucket.latency_coverage < MIN_LATENCY_COVERAGE:
            return None
        if len(state.history) < 3:
            return None

        mean, stddev = state.baseline_latency()
        if stddev == 0:
            return None

        z = (bucket.avg_latency_ms - mean) / stddev
        if z < state.z_score_threshold:
            return None
        if state.should_suppress():
            return None

        severity = "critical" if z > 6.0 else "warning"
        anomaly = AnomalyEvent(
            timestamp=iso(utcnow()),
            anomaly_type="latency_spike",
            service=state.service,
            severity=severity,
            z_score=round(z, 4),
            current_value=round(bucket.avg_latency_ms, 4),
            baseline_mean=round(mean, 4),
            baseline_stddev=round(stddev, 4),
            window_seconds=state.bucket_duration_s,
            sample_count=bucket.latency_sample_count,
            threshold_used=state.z_score_threshold,
            sampled_trace_ids=list(bucket.sampled_trace_ids),
        )
        state.record_anomaly()
        return anomaly
