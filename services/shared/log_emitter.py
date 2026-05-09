"""Profile-aware structured log emitter.

Each service constructs one ``LogEmitter`` at startup. The emitter:

* loads ``sim_profiles.yaml`` and pins to a single service profile,
* watches the runtime scenario file for live updates from the load generator,
* produces JSON ``LogEvent`` messages to a Kafka topic,
* applies the active scenario's injection (error spike, retry storm, silence).

The emitter has no opinions about traffic shape — services drive the loop and
call :meth:`emit_request` to record one synthetic request.
"""

from __future__ import annotations

import json
import logging
import os
import random
import socket
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

import yaml
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

from .schemas import LogEvent, ScenarioState, ServiceProfile, new_trace_id


log = logging.getLogger(__name__)


HTTP_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH")
HTTP_PATHS_BY_SERVICE = {
    "auth-service": ("/login", "/logout", "/token/refresh", "/users/me", "/signup"),
    "api-gateway": ("/v1/orders", "/v1/products", "/v1/cart", "/v1/checkout", "/v1/search"),
    "worker-service": ("/jobs/process", "/jobs/retry", "/jobs/status", "/jobs/cleanup"),
}
DEFAULT_PATHS = ("/health", "/metrics")


class ProfileLoader:
    """Loads sim_profiles.yaml once and exposes a per-service view."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        with self.path.open("r") as fh:
            self._raw: Dict[str, Any] = yaml.safe_load(fh)

    def profile(self, service: str) -> ServiceProfile:
        profiles = self._raw.get("profiles", {})
        if service not in profiles:
            raise KeyError(f"no profile for service {service!r} in {self.path}")
        return ServiceProfile.from_yaml_entry(service, profiles[service])

    def runtime_config(self) -> Dict[str, Any]:
        return self._raw.get("runtime", {}) or {}


class ScenarioWatcher:
    """Reads the shared scenario state file. Tolerant of missing/partial files."""

    def __init__(self, state_file: str | Path, refresh_s: float = 1.0):
        self.state_file = Path(state_file)
        self.refresh_s = refresh_s
        self._cached = ScenarioState()
        self._cached_mtime: float = 0.0
        self._last_check = 0.0
        self._lock = Lock()

    def current(self) -> ScenarioState:
        now = time.monotonic()
        with self._lock:
            if now - self._last_check < self.refresh_s:
                return self._cached
            self._last_check = now
            try:
                stat = self.state_file.stat()
            except FileNotFoundError:
                return self._cached
            if stat.st_mtime == self._cached_mtime:
                return self._cached
            try:
                with self.state_file.open("r") as fh:
                    data = json.load(fh)
                self._cached = ScenarioState.from_dict(data)
                self._cached_mtime = stat.st_mtime
            except (json.JSONDecodeError, OSError) as exc:
                # Don't poison the cache on a partial write — keep the old value.
                log.warning("scenario file unreadable, keeping previous: %s", exc)
            return self._cached


class KafkaEmitter:
    """Thin Kafka producer wrapper with retry-on-startup."""

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        *,
        client_id: str,
        max_attempts: int = 30,
        base_delay_s: float = 1.0,
    ):
        self.topic = topic
        self.bootstrap_servers = bootstrap_servers
        self.client_id = client_id
        self._producer = self._connect(max_attempts, base_delay_s)

    def _connect(self, max_attempts: int, base_delay_s: float) -> KafkaProducer:
        attempt = 0
        while True:
            try:
                return KafkaProducer(
                    bootstrap_servers=self.bootstrap_servers,
                    client_id=self.client_id,
                    value_serializer=lambda v: v.encode("utf-8") if isinstance(v, str) else v,
                    key_serializer=lambda v: v.encode("utf-8") if isinstance(v, str) else v,
                    acks="all",
                    linger_ms=20,
                    retries=5,
                )
            except NoBrokersAvailable:
                attempt += 1
                if attempt >= max_attempts:
                    raise
                delay = min(30.0, base_delay_s * (2 ** min(attempt, 5)))
                log.warning(
                    "kafka not ready (attempt %d/%d), retrying in %.1fs",
                    attempt, max_attempts, delay,
                )
                time.sleep(delay)

    def send(self, event: LogEvent) -> None:
        self._producer.send(self.topic, key=event.service, value=event.to_json())

    def flush(self, timeout: Optional[float] = None) -> None:
        self._producer.flush(timeout=timeout)

    def close(self) -> None:
        self._producer.flush(timeout=5)
        self._producer.close(timeout=5)


class LogEmitter:
    """High-level emitter used by services."""

    def __init__(
        self,
        service: str,
        *,
        profiles_path: str | Path = "/app/sim_profiles.yaml",
        bootstrap_servers: Optional[str] = None,
        topic: Optional[str] = None,
        scenario_file: Optional[str] = None,
        host: Optional[str] = None,
    ):
        self.service = service
        self.host = host or socket.gethostname()

        self.profiles = ProfileLoader(profiles_path)
        runtime = self.profiles.runtime_config()
        self.profile: ServiceProfile = self.profiles.profile(service)

        self.topic = topic or os.getenv("KAFKA_TOPIC") or runtime.get("kafka_topic", "logs.raw")
        self.bootstrap = (
            bootstrap_servers
            or os.getenv("KAFKA_BOOTSTRAP_SERVERS")
            or "kafka:9092"
        )

        scenario_path = (
            scenario_file
            or os.getenv("SCENARIO_STATE_FILE")
            or runtime.get("scenario_state_file", "/shared/scenario.json")
        )
        self.scenario = ScenarioWatcher(scenario_path)

        self.kafka = KafkaEmitter(
            self.bootstrap,
            self.topic,
            client_id=f"{service}-emitter",
        )

        self._injection_started_at: Optional[float] = None

    # ------------------------------------------------------------------
    # Scenario evaluation
    # ------------------------------------------------------------------
    def _active_injection(self) -> Optional[str]:
        """Return the injection string if this service is currently affected."""
        state = self.scenario.current()
        if state.name == "normal" or state.inject is None:
            self._injection_started_at = None
            return None

        targets_us = (
            state.target_service == self.service
            or state.target_service in (None, "all")
        )
        if not targets_us:
            self._injection_started_at = None
            return None

        if self._injection_started_at is None:
            self._injection_started_at = time.monotonic()

        if state.duration_s is not None:
            elapsed = time.monotonic() - self._injection_started_at
            if elapsed > state.duration_s:
                return None

        return state.inject

    def current_error_rate(self) -> float:
        injection = self._active_injection()
        if injection in ("error_spike", "retry_storm", "random"):
            return self.profile.spike_error_rate
        return self.profile.baseline_error_rate

    def current_latency_ms(self, *, errored: bool) -> float:
        injection = self._active_injection()
        if injection in ("error_spike", "retry_storm", "random") or errored:
            base = self.profile.latency_spike_ms
        else:
            base = self.profile.latency_baseline_ms
        # Lognormal-ish jitter so percentiles look realistic.
        return max(1.0, random.gauss(base, base * 0.25))

    def rps_multiplier(self) -> float:
        state = self.scenario.current()
        if (
            state.inject == "retry_storm"
            and (state.target_service == self.service or state.target_service == "all")
        ):
            return state.rps_multiplier or 1.0
        return 1.0

    def is_silenced(self) -> bool:
        return self._active_injection() == "silence"

    # ------------------------------------------------------------------
    # Emission
    # ------------------------------------------------------------------
    def emit_request(self, *, trace_id: Optional[str] = None) -> Optional[LogEvent]:
        """Generate and send one synthetic request log. Returns the event or None when silenced."""
        if self.is_silenced():
            return None

        trace_id = trace_id or new_trace_id()
        method = random.choice(HTTP_METHODS)
        path = random.choice(HTTP_PATHS_BY_SERVICE.get(self.service, DEFAULT_PATHS))
        errored = random.random() < self.current_error_rate()
        duration = self.current_latency_ms(errored=errored)

        if errored:
            status = random.choice((500, 502, 503, 504))
            level = "error" if status >= 500 else "warn"
            message = f"{method} {path} failed with {status}"
        else:
            status = random.choice((200, 200, 200, 201, 204))
            level = "info"
            message = f"{method} {path} ok"

        event = LogEvent.make(
            service=self.service,
            level=level,
            message=message,
            trace_id=trace_id,
            duration_ms=round(duration, 2),
            http_method=method,
            http_status=status,
            http_path=path,
            host=self.host,
        )
        self.kafka.send(event)
        return event

    def emit_raw(
        self,
        level: str,
        message: str,
        *,
        trace_id: Optional[str] = None,
        **fields: Any,
    ) -> LogEvent:
        """Emit a free-form log line (startup, lifecycle, custom events)."""
        event = LogEvent.make(
            service=self.service,
            level=level,
            message=message,
            trace_id=trace_id,
            host=self.host,
            **fields,
        )
        self.kafka.send(event)
        return event

    def close(self) -> None:
        self.kafka.close()
