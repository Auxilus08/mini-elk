"""/logs endpoints — search and anomaly-window drill-down."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from deps import get_es_client
from es_client import ESClient
from schemas import LogEventResponse, LogSearchResponse


router = APIRouter(prefix="/logs", tags=["logs"])


def _hits_to_logs(es_response: dict) -> list[LogEventResponse]:
    return [LogEventResponse(**h["_source"]) for h in es_response["hits"]["hits"]]


def _total(es_response: dict) -> int:
    total = es_response.get("hits", {}).get("total", 0)
    if isinstance(total, dict):
        return int(total.get("value", 0))
    return int(total)


@router.get("/search", response_model=LogSearchResponse)
async def search_logs(
    service: Optional[str] = Query(None),
    level: Optional[str] = Query(None, pattern="^(debug|info|warn|error|critical)$"),
    from_ts: Optional[datetime] = Query(None, alias="from"),
    to_ts: Optional[datetime] = Query(None, alias="to"),
    q: Optional[str] = Query(None, description="free-text search on the message field"),
    size: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    es: ESClient = Depends(get_es_client),
) -> LogSearchResponse:
    result = await es.search_logs(
        service=service,
        level=level,
        from_ts=from_ts,
        to_ts=to_ts,
        query_string=q,
        size=size,
        from_offset=offset,
    )
    return LogSearchResponse(total=_total(result), hits=_hits_to_logs(result))


@router.get("/anomaly-window/{anomaly_id}", response_model=LogSearchResponse)
async def get_anomaly_window(
    anomaly_id: str,
    level: Optional[str] = Query(None, pattern="^(debug|info|warn|error|critical)$"),
    size: int = Query(200, ge=1, le=1000),
    es: ESClient = Depends(get_es_client),
) -> LogSearchResponse:
    """Fetch the anomaly to learn its (service, timestamp), then return logs in
    a ±anomaly_window_minutes window around it. Phase 1 drill-down endpoint."""
    anomaly_hit = await es.get_anomaly_by_id(anomaly_id)
    if anomaly_hit is None:
        raise HTTPException(status_code=404, detail=f"anomaly {anomaly_id!r} not found")
    src = anomaly_hit["_source"]
    service = src["service"]
    ts_str = src["@timestamp"]
    anomaly_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    window = es.settings.anomaly_window_minutes

    result = await es.get_anomaly_window_logs(
        service=service,
        anomaly_ts=anomaly_ts,
        window_minutes=window,
        level=level,
        size=size,
    )
    return LogSearchResponse(
        total=_total(result),
        hits=_hits_to_logs(result),
        anomaly_id=anomaly_id,
    )
