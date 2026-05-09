"""Log-volume detector — fires on traffic spike or sudden silence."""

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

SILENCE_BASELINE_FLOOR = 5.0  # only call zero a "silence" if normal traffic is meaningful


class LogVolumeAnomalyDetector(Detector):
    name = "log_volume"

    def evaluate(
        self,
        event: Optional[LogEvent],
        state: ServiceWindowState,
        flushed_bucket: Optional[BucketAccumulator],
    ) -> Optional[AnomalyEvent]:
        if flushed_bucket is None:
            return None
        if len(state.history) < 3:
            return None

        bucket = flushed_bucket
        mean, stddev = state.baseline_volume()

        # Silence: zero events in a full bucket while baseline is non-trivial.
        if bucket.request_count == 0 and mean >= SILENCE_BASELINE_FLOOR:
            if state.should_suppress():
                return None
            anomaly = AnomalyEvent(
                timestamp=iso(utcnow()),
                anomaly_type="service_silence",
                service=state.service,
                severity="critical",
                z_score=-float("inf") if stddev == 0 else round((0 - mean) / stddev, 4),
                current_value=0.0,
                baseline_mean=round(mean, 4),
                baseline_stddev=round(stddev, 4),
                window_seconds=state.bucket_duration_s,
                sample_count=0,
                threshold_used=state.z_score_threshold,
                sampled_trace_ids=[],
            )
            state.record_anomaly()
            return anomaly

        # Volume spike: z-score above threshold on request_count.
        if stddev == 0:
            return None
        z = (bucket.request_count - mean) / stddev
        if z < state.z_score_threshold:
            return None
        if state.should_suppress():
            return None

        severity = "critical" if z > 6.0 else "warning"
        anomaly = AnomalyEvent(
            timestamp=iso(utcnow()),
            anomaly_type="log_volume_spike",
            service=state.service,
            severity=severity,
            z_score=round(z, 4),
            current_value=float(bucket.request_count),
            baseline_mean=round(mean, 4),
            baseline_stddev=round(stddev, 4),
            window_seconds=state.bucket_duration_s,
            sample_count=bucket.request_count,
            threshold_used=state.z_score_threshold,
            sampled_trace_ids=list(bucket.sampled_trace_ids),
        )
        state.record_anomaly()
        return anomaly
