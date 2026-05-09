"""Async, batching Elasticsearch writer.

Bootstraps explicit index templates so dynamic mapping never silently turns
``trace_id`` into a tokenised text field. Routes ``LogEvent`` to ``logs-*`` and
``AnomalyEvent`` to ``anomalies-*`` daily indices.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple, Union

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk

from .schemas import AnomalyEvent, LogEvent


log = logging.getLogger(__name__)


LOGS_TEMPLATE_NAME = "mini-elk-logs"
ANOMALIES_TEMPLATE_NAME = "mini-elk-anomalies"
LOGS_INDEX_PATTERN = "logs-*"
ANOMALIES_INDEX_PATTERN = "anomalies-*"

LOGS_MAPPING: Dict[str, Any] = {
    "properties": {
        "@timestamp":  {"type": "date"},
        "service":     {"type": "keyword"},
        "level":       {"type": "keyword"},
        "message":     {
            "type": "text",
            "fields": {"raw": {"type": "keyword", "ignore_above": 1024}},
        },
        "trace_id":    {"type": "keyword"},
        "duration_ms": {"type": "float"},
        "http_method": {"type": "keyword"},
        "http_status": {"type": "short"},
        "http_path":   {"type": "keyword"},
        "host":        {"type": "keyword"},
    }
}

ANOMALIES_MAPPING: Dict[str, Any] = {
    "properties": {
        "@timestamp":         {"type": "date"},
        "id":                 {"type": "keyword"},
        "anomaly_type":       {"type": "keyword"},
        "service":            {"type": "keyword"},
        "severity":           {"type": "keyword"},
        "z_score":            {"type": "float"},
        "current_value":      {"type": "float"},
        "baseline_mean":      {"type": "float"},
        "baseline_stddev":    {"type": "float"},
        "window_seconds":     {"type": "integer"},
        "sample_count":       {"type": "integer"},
        "threshold_used":     {"type": "float"},
        "sampled_trace_ids":  {"type": "keyword"},
        "resolved":           {"type": "boolean"},
    }
}

INDEX_SETTINGS = {"number_of_shards": 1, "number_of_replicas": 0}


def _daily_index(prefix: str, when: datetime) -> str:
    return f"{prefix}-{when.strftime('%Y.%m.%d')}"


async def connect_with_backoff(
    url: str,
    *,
    max_attempts: int = 30,
    base_delay_s: float = 2.0,
    cap_s: float = 30.0,
) -> AsyncElasticsearch:
    attempt = 0
    while True:
        client = AsyncElasticsearch(url, request_timeout=10)
        try:
            info = await client.info()
            log.info("connected to elasticsearch %s", info.get("version", {}).get("number"))
            return client
        except Exception as exc:  # noqa: BLE001
            await client.close()
            attempt += 1
            if attempt >= max_attempts:
                log.error("giving up on elasticsearch after %d attempts: %s", attempt, exc)
                raise
            delay = min(cap_s, base_delay_s * (2 ** min(attempt, 4)))
            log.warning("elasticsearch not ready (attempt %d/%d): %s — retrying in %.1fs",
                        attempt, max_attempts, exc, delay)
            await asyncio.sleep(delay)


class ESWriter:
    def __init__(
        self,
        client: AsyncElasticsearch,
        *,
        bulk_size: int = 100,
        flush_interval_s: float = 5.0,
    ):
        self.client = client
        self.bulk_size = bulk_size
        self.flush_interval_s = flush_interval_s
        self._buffer: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self._stopped = False

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------
    async def bootstrap(self) -> None:
        await self._ensure_template(
            LOGS_TEMPLATE_NAME, LOGS_INDEX_PATTERN, LOGS_MAPPING,
        )
        await self._ensure_template(
            ANOMALIES_TEMPLATE_NAME, ANOMALIES_INDEX_PATTERN, ANOMALIES_MAPPING,
        )
        self._flush_task = asyncio.create_task(self._periodic_flush())

    async def _ensure_template(
        self,
        name: str,
        pattern: str,
        mapping: Dict[str, Any],
    ) -> None:
        body = {
            "index_patterns": [pattern],
            "priority": 100,
            "template": {
                "settings": INDEX_SETTINGS,
                "mappings": mapping,
            },
        }
        await self.client.indices.put_index_template(name=name, body=body)
        log.info("ensured index template %s for %s", name, pattern)

    # ------------------------------------------------------------------
    # Public write API
    # ------------------------------------------------------------------
    async def write_log(self, event: LogEvent) -> None:
        idx = _daily_index("logs", _parse_ts(event.timestamp))
        await self._enqueue({"_index": idx, "_source": event.to_es_doc()})

    async def write_anomaly(self, anomaly: AnomalyEvent) -> None:
        idx = _daily_index("anomalies", _parse_ts(anomaly.timestamp))
        await self._enqueue({
            "_index": idx,
            "_id": anomaly.id,
            "_source": anomaly.to_dict(),
        })

    async def _enqueue(self, action: Dict[str, Any]) -> None:
        async with self._lock:
            self._buffer.append(action)
            ready = len(self._buffer) >= self.bulk_size
        if ready:
            await self.flush()

    # ------------------------------------------------------------------
    # Flushing
    # ------------------------------------------------------------------
    async def _periodic_flush(self) -> None:
        try:
            while not self._stopped:
                await asyncio.sleep(self.flush_interval_s)
                await self.flush()
        except asyncio.CancelledError:
            pass

    async def flush(self) -> None:
        async with self._lock:
            if not self._buffer:
                return
            batch = self._buffer
            self._buffer = []
        await self._send_with_retry(batch)

    async def _send_with_retry(self, batch: List[Dict[str, Any]]) -> None:
        try:
            await self._send(batch)
        except Exception as exc:  # noqa: BLE001 — connection-level
            log.warning("bulk send failed (%s) — retrying once in 2s", exc)
            await asyncio.sleep(2.0)
            try:
                await self._send(batch)
            except Exception:
                log.exception("bulk send failed on retry — dropping %d docs", len(batch))

    async def _send(self, batch: List[Dict[str, Any]]) -> None:
        success, errors = await async_bulk(
            self.client,
            batch,
            raise_on_error=False,
            raise_on_exception=False,
        )
        if errors:
            for err in errors:
                op = next(iter(err.values())) if isinstance(err, dict) else err
                log.warning("es bulk error: id=%s reason=%s",
                            (op or {}).get("_id") if isinstance(op, dict) else None,
                            (op or {}).get("error") if isinstance(op, dict) else op)
        log.debug("flushed %d docs (failed=%d)", success, len(errors) if errors else 0)

    # ------------------------------------------------------------------
    async def close(self) -> None:
        self._stopped = True
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self.flush()
        await self.client.close()


def _parse_ts(ts: str) -> datetime:
    candidate = ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
