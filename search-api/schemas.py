"""Pydantic response models — every endpoint returns one of these."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class LogEventResponse(BaseModel):
    # Accept ES's "@timestamp" on input; serialize as "timestamp" so JS clients
    # don't have to use bracket notation for a single awkward field.
    timestamp: datetime = Field(validation_alias="@timestamp")
    service: str
    level: str
    message: str
    trace_id: str
    duration_ms: Optional[float] = None
    http_method: Optional[str] = None
    http_status: Optional[int] = None
    http_path: Optional[str] = None
    host: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class LogSearchResponse(BaseModel):
    total: int
    hits: List[LogEventResponse]
    anomaly_id: Optional[str] = None  # echoed back for drill-down context


class AnomalyResponse(BaseModel):
    id: str
    timestamp: datetime = Field(validation_alias="@timestamp")
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
    sampled_trace_ids: List[str] = Field(default_factory=list)
    resolved: bool = False

    model_config = ConfigDict(populate_by_name=True)


class AnomalyListResponse(BaseModel):
    total: int
    anomalies: List[AnomalyResponse]


class ServiceHealthSummary(BaseModel):
    service: str
    status: str  # healthy | degraded | anomalous
    error_rate_1m: float
    log_volume_1m: int
    last_anomaly_at: Optional[datetime] = None
    last_anomaly_type: Optional[str] = None


class HealthResponse(BaseModel):
    status: str  # ok | degraded
    es_cluster_status: str
    services: List[ServiceHealthSummary]
    uptime_seconds: float
