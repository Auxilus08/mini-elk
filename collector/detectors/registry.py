"""Fan-out orchestrator.

The registry owns the contract: ``state.ingest(event)`` is called *once*, and
the resulting flushed bucket (if any) is passed to every detector. Detector
exceptions are swallowed and logged so a single broken detector cannot stop
the pipeline.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from collector.core.schemas import (
    AnomalyEvent,
    BucketAccumulator,
    LogEvent,
    ServiceWindowState,
)
from .base import Detector


log = logging.getLogger(__name__)


class DetectorRegistry:
    def __init__(self, detectors: List[Detector]):
        self.detectors = list(detectors)

    def run(self, event: LogEvent, state: ServiceWindowState) -> List[AnomalyEvent]:
        flushed_list = state.ingest(event)
        return self._evaluate_all(event, state, flushed_list)

    def run_tick(self, state: ServiceWindowState) -> List[AnomalyEvent]:
        """Drive the clock forward without an event (for silence detection)."""
        flushed_list = state.tick()
        if not flushed_list:
            return []
        return self._evaluate_all(None, state, flushed_list)

    def _evaluate_all(
        self,
        event: Optional[LogEvent],
        state: ServiceWindowState,
        flushed_list: List[BucketAccumulator],
    ) -> List[AnomalyEvent]:
        out: List[AnomalyEvent] = []
        # Always run detectors at least once — some short-circuit when
        # flushed_bucket is None and that's a valid no-op.
        targets: List[Optional[BucketAccumulator]] = (
            list(flushed_list) if flushed_list else [None]
        )
        for fb in targets:
            for detector in self.detectors:
                try:
                    anomaly = detector.evaluate(event, state, fb)
                except Exception:  # noqa: BLE001 — must not crash pipeline
                    log.exception("detector %s raised; ignoring", detector.name)
                    continue
                if anomaly is not None:
                    out.append(anomaly)
        return out
