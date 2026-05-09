"""worker-service — emits background-job processing logs.

Lower RPS, longer per-job duration, higher baseline error rate. Emits a final
"Worker process restarting" error log on the transition into a silence
injection so the trail of evidence is realistic.
"""

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
    format="%(asctime)s %(levelname)s worker-service %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("worker-service")


SERVICE = "worker-service"

JOB_TYPES = [
    "send_email",
    "process_payment",
    "generate_report",
    "sync_inventory",
    "cleanup_sessions",
    "index_documents",
]

ERROR_TEMPLATES = [
    "Job {job_type} failed: database timeout",
    "Job {job_type} failed: dependency unavailable",
    "Job {job_type} exceeded max retries",
    "Dead letter queue threshold reached",
    "Worker OOM on job {job_type}",
]

INFO_TEMPLATES = [
    "Job {job_type} completed in {duration_ms}ms",
    "Job {job_type} queued",
    "Worker heartbeat",
]

# Worker durations are job-shaped, not HTTP-shaped — much longer than auth/gateway.
JOB_BASELINE_MIN_MS = 200.0
JOB_BASELINE_MAX_MS = 5000.0
JOB_SPIKE_MAX_MS = 15000.0


def _job_duration_ms(emitter: LogEmitter, errored: bool) -> float:
    """Independent latency model — overrides the HTTP-shaped one in LogEmitter."""
    state_inject = emitter.scenario.current().inject
    is_spike = errored or state_inject in ("error_spike", "retry_storm", "random")
    if is_spike:
        return random.uniform(JOB_BASELINE_MAX_MS, JOB_SPIKE_MAX_MS)
    return random.uniform(JOB_BASELINE_MIN_MS, JOB_BASELINE_MAX_MS)


async def run_loop(emitter: LogEmitter) -> None:
    rps = max(1, emitter.profile.traffic_rps)
    base_interval = 1.0 / rps
    log.info("starting loop: rps=%d base_interval=%.4fs", rps, base_interval)

    tick = 0
    was_silenced = False
    while True:
        silenced = emitter.is_silenced()
        if silenced and not was_silenced:
            # One last error log so the audit trail shows *why* the silence began.
            duration = _job_duration_ms(emitter, errored=True)
            emitter.emit_raw(
                "error",
                "Worker process restarting",
                duration_ms=round(duration, 2),
            )
        was_silenced = silenced
        if silenced:
            await asyncio.sleep(1.0)
            continue

        tick += 1

        # Every 10 ticks, surface a debug heartbeat.
        if tick % 10 == 0:
            queue_depth = random.randint(0, 50)
            emitter.emit_raw(
                "debug",
                f"Worker alive, queue depth: {queue_depth}",
            )

        job_type = random.choice(JOB_TYPES)
        errored = random.random() < emitter.current_error_rate()
        duration = _job_duration_ms(emitter, errored=errored)
        trace_id = new_trace_id()

        if errored:
            level = "error"
            template = random.choice(ERROR_TEMPLATES)
        else:
            level = "info"
            template = random.choice(INFO_TEMPLATES)

        message = template.format(job_type=job_type, duration_ms=int(duration))

        emitter.emit_raw(
            level, message,
            trace_id=trace_id,
            duration_ms=round(duration, 2),
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
