"""/health endpoint — used by the dashboard ServiceHealthGrid AND the docker
healthcheck. Aggregates ES cluster status with a per-service log/anomaly view
of the last minute."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Request

from deps import get_es_client
from es_client import ESClient
from schemas import HealthResponse, ServiceHealthSummary


router = APIRouter(tags=["health"])

# Threshold above which a service is considered "degraded" purely from error
# rate alone, even without an active anomaly. Anomaly presence overrides.
DEGRADED_ERROR_RATE = 0.10


def _classify(error_rate: float, has_recent_anomaly: bool) -> str:
    if has_recent_anomaly:
        return "anomalous"
    if error_rate >= DEGRADED_ERROR_RATE:
        return "degraded"
    return "healthy"


def _parse_iso(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


@router.get("/health", response_model=HealthResponse)
async def health(
    request: Request,
    es: ESClient = Depends(get_es_client),
) -> HealthResponse:
    cluster = await es.cluster_health()
    cluster_status = cluster.get("status", "unknown")
    health_data = await es.get_service_health(window_seconds=60)

    log_buckets = (
        health_data["logs_agg"].get("aggregations", {})
        .get("by_service", {}).get("buckets", [])
    )
    anomaly_buckets = (
        health_data["anomalies_agg"].get("aggregations", {})
        .get("by_service", {}).get("buckets", [])
    )

    last_anomaly_by_service: Dict[str, Dict[str, str]] = {}
    for b in anomaly_buckets:
        hits = b.get("latest", {}).get("hits", {}).get("hits", [])
        if not hits:
            continue
        src = hits[0]["_source"]
        last_anomaly_by_service[b["key"]] = {
            "ts": src.get("@timestamp", ""),
            "type": src.get("anomaly_type", ""),
        }

    services: List[ServiceHealthSummary] = []
    for b in log_buckets:
        svc = b["key"]
        total = int(b.get("doc_count", 0))
        errors = int(b.get("errors", {}).get("doc_count", 0))
        rate = (errors / total) if total else 0.0
        last = last_anomaly_by_service.get(svc)
        last_at = _parse_iso(last["ts"]) if last else None
        last_type = last["type"] if last else None
        services.append(ServiceHealthSummary(
            service=svc,
            status=_classify(rate, has_recent_anomaly=last is not None),
            error_rate_1m=round(rate, 4),
            log_volume_1m=total,
            last_anomaly_at=last_at,
            last_anomaly_type=last_type,
        ))

    # Cover services that have a recent anomaly but no logs in the last 60s
    # (e.g. silenced workers) — surface them too.
    seen = {s.service for s in services}
    for svc, last in last_anomaly_by_service.items():
        if svc in seen:
            continue
        services.append(ServiceHealthSummary(
            service=svc,
            status="anomalous",
            error_rate_1m=0.0,
            log_volume_1m=0,
            last_anomaly_at=_parse_iso(last["ts"]),
            last_anomaly_type=last["type"],
        ))

    services.sort(key=lambda s: s.service)
    overall = "ok" if cluster_status in ("green", "yellow") else "degraded"
    uptime = time.time() - getattr(request.app.state, "start_time", time.time())

    return HealthResponse(
        status=overall,
        es_cluster_status=cluster_status,
        services=services,
        uptime_seconds=round(uptime, 2),
    )
