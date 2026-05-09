"""auth-service — emits authentication / token request logs."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import signal
import sys

from shared import LogEmitter, new_trace_id


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s auth-service %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("auth-service")


SERVICE = "auth-service"

ENDPOINTS = [
    ("POST", "/auth/login"),
    ("POST", "/auth/refresh"),
    ("GET",  "/auth/validate"),
    ("POST", "/auth/logout"),
    ("POST", "/auth/register"),
]

ERROR_MESSAGES = [
    "JWT validation failed",
    "Token expired",
    "Invalid credentials",
    "Account locked after failed attempts",
    "OAuth provider unreachable",
    "Session not found",
]

INFO_MESSAGES = [
    "User authenticated successfully",
    "Token refreshed",
    "Session validated",
    "User logged out",
    "New user registered",
]

ERROR_STATUSES = (401, 403, 500, 502, 503, 504)
SUCCESS_STATUSES = (200, 200, 200, 201, 204)
SLOW_AUTH_THRESHOLD_MS = 300.0


async def run_loop(emitter: LogEmitter) -> None:
    rps = max(1, emitter.profile.traffic_rps)
    base_interval = 1.0 / rps
    log.info("starting loop: rps=%d base_interval=%.4fs", rps, base_interval)

    request_count = 0
    while True:
        if emitter.is_silenced():
            await asyncio.sleep(1.0)
            continue

        method, path = random.choice(ENDPOINTS)
        errored = random.random() < emitter.current_error_rate()
        duration = emitter.current_latency_ms(errored=errored)
        trace_id = new_trace_id()

        if errored:
            status = random.choice(ERROR_STATUSES)
            level = "error" if status >= 500 else "warn"
            message = random.choice(ERROR_MESSAGES)
        else:
            status = random.choice(SUCCESS_STATUSES)
            level = "info"
            message = random.choice(INFO_MESSAGES)

        emitter.emit_raw(
            level, message,
            trace_id=trace_id,
            duration_ms=round(duration, 2),
            http_method=method,
            http_status=status,
            http_path=path,
        )
        request_count += 1

        # Every ~50 requests, surface a slow-auth warning carrying duration.
        if request_count % 50 == 0:
            slow = max(SLOW_AUTH_THRESHOLD_MS, duration * 1.5)
            emitter.emit_raw(
                "warn",
                f"Auth latency above threshold: {slow:.1f}ms",
                duration_ms=round(slow, 2),
                http_method=method,
                http_path=path,
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
