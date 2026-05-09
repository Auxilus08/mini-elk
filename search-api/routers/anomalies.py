"""/anomalies endpoints — list, fetch by id, drill-down to logs."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from deps import get_es_client
from es_client import ESClient
from schemas import (
    AnomalyListResponse,
    AnomalyResponse,
    LogEventResponse,
    LogSearchResponse,
)


router = APIRouter(prefix="/anomalies", tags=["anomalies"])


def _hit_to_anomaly(hit: dict) -> AnomalyResponse:
    return AnomalyResponse(**hit["_source"])


def _hits_to_logs(es_response: dict) -> list[LogEventResponse]:
    return [LogEventResponse(**h["_source"]) for h in es_response["hits"]["hits"]]


def _total(es_response: dict) -> int:
    total = es_response.get("hits", {}).get("total", 0)
    if isinstance(total, dict):
        return int(total.get("value", 0))
    return int(total)


# Specific routes BEFORE the wildcard /{anomaly_id} so "recent" doesn't
# get matched as an id.
@router.get("/recent", response_model=AnomalyListResponse)
async def get_recent_anomalies(
    service: Optional[str] = Query(None),
    severity: Optional[str] = Query(None, pattern="^(warning|critical)$"),
    anomaly_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    es: ESClient = Depends(get_es_client),
) -> AnomalyListResponse:
    result = await es.get_recent_anomalies(
        service=service,
        limit=limit,
        severity=severity,
        anomaly_type=anomaly_type,
    )
    hits = result.get("hits", {}).get("hits", [])
    return AnomalyListResponse(
        total=_total(result),
        anomalies=[_hit_to_anomaly(h) for h in hits],
    )


@router.get("/{anomaly_id}", response_model=AnomalyResponse)
async def get_anomaly(
    anomaly_id: str,
    es: ESClient = Depends(get_es_client),
) -> AnomalyResponse:
    hit = await es.get_anomaly_by_id(anomaly_id)
    if hit is None:
        raise HTTPException(status_code=404, detail=f"anomaly {anomaly_id!r} not found")
    return _hit_to_anomaly(hit)


@router.get("/{anomaly_id}/logs", response_model=LogSearchResponse)
async def get_anomaly_logs(
    anomaly_id: str,
    level: Optional[str] = Query(None, pattern="^(debug|info|warn|error|critical)$"),
    size: int = Query(200, ge=1, le=1000),
    es: ESClient = Depends(get_es_client),
) -> LogSearchResponse:
    """Anomaly-centric drill-down. Mirrors /logs/anomaly-window/{id}."""
    hit = await es.get_anomaly_by_id(anomaly_id)
    if hit is None:
        raise HTTPException(status_code=404, detail=f"anomaly {anomaly_id!r} not found")
    src = hit["_source"]
    anomaly_ts = datetime.fromisoformat(src["@timestamp"].replace("Z", "+00:00"))
    result = await es.get_anomaly_window_logs(
        service=src["service"],
        anomaly_ts=anomaly_ts,
        window_minutes=es.settings.anomaly_window_minutes,
        level=level,
        size=size,
    )
    return LogSearchResponse(
        total=_total(result),
        hits=_hits_to_logs(result),
        anomaly_id=anomaly_id,
    )
