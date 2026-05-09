"""Detector ABC.

DEVIATION FROM SPEC: the brief shows ``Detector.ingest(event, state)`` and also
says "call ``state.ingest(event)``" inside each detector. Both can't be true
without each detector mutating shared state once per fan-out (3× the counts).

Resolution: the registry calls ``state.ingest(event)`` exactly once per event
and then invokes ``Detector.evaluate(event, state, flushed_bucket)``. Detectors
read ``flushed_bucket`` (None unless the event crossed a bucket boundary) and
``state.history`` for baselines, but never mutate counts themselves.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from collector.core.schemas import (
    AnomalyEvent,
    BucketAccumulator,
    LogEvent,
    ServiceWindowState,
)


class Detector(ABC):
    """Implementations evaluate one event-or-tick against shared service state."""

    name: str = "detector"

    @abstractmethod
    def evaluate(
        self,
        event: Optional[LogEvent],
        state: ServiceWindowState,
        flushed_bucket: Optional[BucketAccumulator],
    ) -> Optional[AnomalyEvent]:
        """Return an AnomalyEvent if the just-flushed bucket trips this detector."""
