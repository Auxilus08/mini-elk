"""api-gateway — emits proxy/upstream request logs."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import signal
import sys
import uuid

from shared import LogEmitter, new_trace_id


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s api-gateway %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("api-gateway")


SERVICE = "api-gateway"

UPSTREAM_SERVICES = ["user-service", "product-service", "order-service", "payment-service"]

ENDPOINTS = [
    ("GET",    "/api/v1/users/{id}"),
    ("POST",   "/api/v1/orders"),
    ("GET",    "/api/v1/products"),
    ("PUT",    "/api/v1/users/{id}/profile"),
    ("DELETE", "/api/v1/orders/{id}"),
    ("GET",    "/api/v1/payments/status"),
]

ERROR_TEMPLATES = [
    "Upstream {service} returned 503",
    "Request timeout after {duration_ms}ms",
    "Circuit breaker open for {service}",
    "Rate limit exceeded for client",
    "Invalid request payload",
    "Upstream connection refused",
]

INFO_TEMPLATES = [
    "Request proxied to {service}",
    "Response cached",
    "Request completed",
]

ERROR_STATUSES = (500, 502, 503, 504)
SUCCESS_STATUSES = (200, 200, 200, 201, 204)


def _materialise_path(path: str) -> str:
    return path.replace("{id}", uuid.uuid4().hex[:8])


def _format(template: str, *, upstream: str, duration_ms: float) -> str:
    return template.format(service=upstream, duration_ms=int(duration_ms))


async def emit_one(
    emitter: LogEmitter,
    *,
    method: str,
    path: str,
    upstream: str,
    trace_id: str,
    force_error: bool = False,
) -> None:
    """Emit one request log. Returns nothing — caller controls cadence."""
    errored = force_error or (random.random() < emitter.current_error_rate())
    duration = emitter.current_latency_ms(errored=errored)

    if errored:
        status = random.choice(ERROR_STATUSES)
        level = "error" if status >= 500 else "warn"
        message = _format(random.choice(ERROR_TEMPLATES), upstream=upstream, duration_ms=duration)
    else:
        status = random.choice(SUCCESS_STATUSES)
        level = "info"
        message = _format(random.choice(INFO_TEMPLATES), upstream=upstream, duration_ms=duration)

    emitter.emit_raw(
        level, message,
        trace_id=trace_id,
        duration_ms=round(duration, 2),
        http_method=method,
        http_status=status,
        http_path=_materialise_path(path),
    )


def _is_retry_storm(emitter: LogEmitter) -> bool:
    state = emitter.scenario.current()
    if state.inject != "retry_storm":
        return False
    return state.target_service in (None, SERVICE, "all")


async def run_loop(emitter: LogEmitter) -> None:
    rps = max(1, emitter.profile.traffic_rps)
    base_interval = 1.0 / rps
    log.info("starting loop: rps=%d base_interval=%.4fs", rps, base_interval)

    while True:
        if emitter.is_silenced():
            await asyncio.sleep(1.0)
            continue

        method, path = random.choice(ENDPOINTS)
        upstream = random.choice(UPSTREAM_SERVICES)
        trace_id = new_trace_id()

        if _is_retry_storm(emitter):
            # Burst 2–5 requests on the same trace_id to look like client retries.
            burst = random.randint(2, 5)
            for i in range(burst):
                # First N-1 retries are forced errors, final attempt mirrors the
                # natural error rate so successes are still possible.
                force_err = i < burst - 1
                await emit_one(
                    emitter,
                    method=method, path=path, upstream=upstream,
                    trace_id=trace_id, force_error=force_err,
                )
                await asyncio.sleep(0.01)  # tight retry loop, ~10ms apart
        else:
            await emit_one(
                emitter,
                method=method, path=path, upstream=upstream,
                trace_id=trace_id,
            )

        multiplier = max(0.1, emitter.rps_multiplier())
        await asyncio.sleep(base_interval / multiplier)


async def amain() -> None:
    emitter = LogEmitter(
        SERVICE,
        profiles_path=os.getenv("PROFILES_PATH", "/app/sim_profiles.yaml"),
    )
    log.info("emitter ready: bootstrap=%s topic=%s profile=%s",
             emitter.bootstrap, emitter.topic, emitter.profile)
    emitter.emit_raw("info", "Service starting up")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    runner = asyncio.create_task(run_loop(emitter))
    await stop.wait()
    runner.cancel()
    try:
        await runner
    except asyncio.CancelledError:
        pass
    emitter.close()


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
