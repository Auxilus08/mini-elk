"""Async ES client wrapper.

The wrapper does three jobs:
  1. Hide elasticsearch-py kwargs from the routers (they speak parameters).
  2. Tolerate the ``index_not_found_exception`` that fires before the collector
     has written its first doc — translate to empty results, not 500s.
  3. Centralise the index/sort/range query construction so the routers stay
     thin and trivially testable.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from elasticsearch import AsyncElasticsearch, NotFoundError, ApiError

from config import Settings


log = logging.getLogger(__name__)


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _empty_search() -> Dict[str, Any]:
    return {"hits": {"total": {"value": 0}, "hits": []}}


class ESClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Optional[AsyncElasticsearch] = None

    @property
    def client(self) -> AsyncElasticsearch:
        if self._client is None:
            raise RuntimeError("ESClient.connect() must be awaited before use")
        return self._client

    # ------------------------------------------------------------------
    async def connect(self) -> None:
        max_attempts = 30
        base_delay = 2.0
        cap = 30.0
        attempt = 0
        while True:
            client = AsyncElasticsearch(
                self.settings.es_host,
                request_timeout=self.settings.es_timeout,
            )
            try:
                info = await client.info()
                log.info("connected to elasticsearch %s",
                         info.get("version", {}).get("number"))
                self._client = client
                return
            except Exception as exc:  # noqa: BLE001
                await client.close()
                attempt += 1
                if attempt >= max_attempts:
                    raise RuntimeError(
                        f"could not reach elasticsearch at {self.settings.es_host} "
                        f"after {attempt} attempts: {exc}"
                    )
                delay = min(cap, base_delay * (2 ** min(attempt, 4)))
                log.warning("es not ready (attempt %d/%d): %s — retrying in %.1fs",
                            attempt, max_attempts, exc, delay)
                await asyncio.sleep(delay)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    # ------------------------------------------------------------------
    # Cluster
    # ------------------------------------------------------------------
    async def cluster_health(self) -> Dict[str, Any]:
        try:
            return await self.client.cluster.health()
        except Exception as exc:  # noqa: BLE001
            log.warning("cluster.health failed: %s", exc)
            return {"status": "red"}

    # ------------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------------
    async def search_logs(
        self,
        *,
        service: Optional[str],
        level: Optional[str],
        from_ts: Optional[datetime],
        to_ts: Optional[datetime],
        query_string: Optional[str],
        size: int,
        from_offset: int,
    ) -> Dict[str, Any]:
        must: List[Dict[str, Any]] = []
        if service:
            must.append({"term": {"service": service}})
        if level:
            must.append({"term": {"level": level}})
        if query_string:
            must.append({
                "query_string": {"query": query_string, "default_field": "message"}
            })
        if from_ts or to_ts:
            rng: Dict[str, str] = {}
            if from_ts:
                rng["gte"] = _utc(from_ts).isoformat()
            if to_ts:
                rng["lte"] = _utc(to_ts).isoformat()
            must.append({"range": {"@timestamp": rng}})

        body: Dict[str, Any] = {
            "query": {"bool": {"must": must}} if must else {"match_all": {}},
            "sort": [{"@timestamp": {"order": "desc"}}, {"_doc": {"order": "asc"}}],
            "size": size,
            "from": from_offset,
            "track_total_hits": True,
        }
        return await self._safe_search(self.settings.es_index_logs, body)

    async def get_anomaly_window_logs(
        self,
        *,
        service: str,
        anomaly_ts: datetime,
        window_minutes: int,
        level: Optional[str],
        size: int,
    ) -> Dict[str, Any]:
        anomaly_ts = _utc(anomaly_ts)
        lo = anomaly_ts - timedelta(minutes=window_minutes)
        hi = anomaly_ts + timedelta(minutes=window_minutes)
        must: List[Dict[str, Any]] = [
            {"term": {"service": service}},
            {"range": {"@timestamp": {"gte": lo.isoformat(), "lte": hi.isoformat()}}},
        ]
        if level:
            must.append({"term": {"level": level}})
        body: Dict[str, Any] = {
            "query": {"bool": {"must": must}},
            "sort": [{"@timestamp": {"order": "asc"}}],
            "size": size,
            "track_total_hits": True,
        }
        return await self._safe_search(self.settings.es_index_logs, body)

    # ------------------------------------------------------------------
    # Anomalies
    # ------------------------------------------------------------------
    async def get_recent_anomalies(
        self,
        *,
        service: Optional[str],
        limit: int,
        severity: Optional[str],
        anomaly_type: Optional[str],
    ) -> Dict[str, Any]:
        must: List[Dict[str, Any]] = []
        if service:
            must.append({"term": {"service": service}})
        if severity:
            must.append({"term": {"severity": severity}})
        if anomaly_type:
            must.append({"term": {"anomaly_type": anomaly_type}})
        body: Dict[str, Any] = {
            "query": {"bool": {"must": must}} if must else {"match_all": {}},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": limit,
            "track_total_hits": True,
        }
        return await self._safe_search(self.settings.es_index_anomalies, body)

    async def get_anomaly_by_id(self, anomaly_id: str) -> Optional[Dict[str, Any]]:
        # The doc lives in a daily index — search by the `id` field instead of
        # GET-by-_id so we don't need to know which day.
        body = {
            "query": {"term": {"id": anomaly_id}},
            "size": 1,
        }
        result = await self._safe_search(self.settings.es_index_anomalies, body)
        hits = result.get("hits", {}).get("hits", [])
        if not hits:
            return None
        return hits[0]

    # ------------------------------------------------------------------
    # Service health
    # ------------------------------------------------------------------
    async def get_service_health(self, *, window_seconds: int = 60) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        lo = now - timedelta(seconds=window_seconds)

        logs_body: Dict[str, Any] = {
            "size": 0,
            "query": {"range": {"@timestamp": {"gte": lo.isoformat()}}},
            "aggs": {
                "by_service": {
                    "terms": {"field": "service", "size": 50},
                    "aggs": {
                        "errors": {
                            "filter": {"terms": {"level": ["error", "critical"]}}
                        }
                    },
                }
            },
        }
        logs_agg = await self._safe_search(self.settings.es_index_logs, logs_body)

        # Most recent anomaly per service (last 1h is plenty for status).
        anomalies_body: Dict[str, Any] = {
            "size": 0,
            "query": {"range": {"@timestamp": {"gte": (now - timedelta(hours=1)).isoformat()}}},
            "aggs": {
                "by_service": {
                    "terms": {"field": "service", "size": 50},
                    "aggs": {
                        "latest": {
                            "top_hits": {
                                "sort": [{"@timestamp": {"order": "desc"}}],
                                "size": 1,
                                "_source": {"includes": ["@timestamp", "anomaly_type"]},
                            }
                        }
                    },
                }
            },
        }
        anomalies_agg = await self._safe_search(self.settings.es_index_anomalies, anomalies_body)

        return {
            "logs_agg": logs_agg,
            "anomalies_agg": anomalies_agg,
            "window_seconds": window_seconds,
        }

    # ------------------------------------------------------------------
    async def _safe_search(self, index: str, body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = await self.client.search(index=index, body=body)
        except NotFoundError:
            return _empty_search()
        except ApiError as exc:
            # index_not_found is reported as ApiError in some es-py versions.
            if getattr(exc, "status_code", None) == 404:
                return _empty_search()
            log.exception("es search failed: index=%s body=%s", index, body)
            raise
        # AsyncElasticsearch returns ObjectApiResponse — convert to dict.
        if hasattr(response, "body"):
            return response.body
        return dict(response)
