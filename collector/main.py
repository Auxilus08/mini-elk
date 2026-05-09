"""Collector entrypoint — wires Kafka, normaliser, registry, and ES.

The Kafka client (confluent-kafka) is sync, so it runs on a worker thread that
hands raw payloads to an asyncio queue. The asyncio main loop normalises,
fans out to detectors, and writes to ES.

Offset commit policy: at-least-once. We commit the offset of a message only
after its log has been queued for ES write (i.e. accepted by ESWriter) and any
resulting anomalies have been queued too.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import threading
import time
from typing import Dict, Optional, Tuple

from confluent_kafka import Consumer, KafkaError, KafkaException, Message, TopicPartition

from collector.core import normaliser
from collector.core.es_writer import ESWriter, connect_with_backoff
from collector.core.schemas import LogEvent, ServiceWindowState
from collector.detectors.base import Detector
from collector.detectors.error_rate import ErrorRateSpikeDetector
from collector.detectors.latency import LatencySpikeDetector
from collector.detectors.log_volume import LogVolumeAnomalyDetector
from collector.detectors.registry import DetectorRegistry


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("collector")


KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "logs.raw")
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_GROUP = os.getenv("KAFKA_GROUP", "collector-group")
ES_URL = os.getenv("ELASTICSEARCH_URL", "http://elasticsearch:9200")
TICK_INTERVAL_S = float(os.getenv("TICK_INTERVAL_S", "30"))


def build_detectors() -> list[Detector]:
    return [
        ErrorRateSpikeDetector(),
        LogVolumeAnomalyDetector(),
        LatencySpikeDetector(),
    ]


# ---------------------------------------------------------------------------
# Kafka thread → asyncio bridge
# ---------------------------------------------------------------------------
class KafkaBridge:
    """Sync confluent-kafka consumer running on a worker thread.

    Pushes ``(message, raw_value)`` tuples to an asyncio queue. The main loop
    drains the queue, processes, then schedules the offset commit back via
    ``loop.call_soon_threadsafe``.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue,
        *,
        topic: str,
        bootstrap: str,
        group: str,
    ):
        self.loop = loop
        self.queue = queue
        self.topic = topic
        self.bootstrap = bootstrap
        self.group = group
        self._consumer: Optional[Consumer] = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="kafka-consumer", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def commit(self, message: Message) -> None:
        if self._consumer is None:
            return
        try:
            self._consumer.commit(message=message, asynchronous=True)
        except KafkaException as exc:
            log.warning("kafka commit failed: %s", exc)

    # ------------------------------------------------------------------
    def _connect_with_backoff(self) -> Consumer:
        attempt = 0
        base_delay = 2.0
        cap = 30.0
        while not self._stop.is_set():
            try:
                consumer = Consumer({
                    "bootstrap.servers": self.bootstrap,
                    "group.id": self.group,
                    "enable.auto.commit": False,
                    "auto.offset.reset": "earliest",
                    "session.timeout.ms": 30000,
                })
                consumer.subscribe([self.topic])
                # Force a metadata fetch to fail fast if the broker is down.
                consumer.list_topics(timeout=5.0)
                log.info("kafka consumer ready (topic=%s group=%s)", self.topic, self.group)
                return consumer
            except KafkaException as exc:
                attempt += 1
                delay = min(cap, base_delay * (2 ** min(attempt, 4)))
                log.warning("kafka not ready (attempt %d): %s — retrying in %.1fs",
                            attempt, exc, delay)
                time.sleep(delay)
        raise RuntimeError("stopped before kafka was ready")

    def _run(self) -> None:
        try:
            self._consumer = self._connect_with_backoff()
        except Exception:
            log.exception("kafka consumer failed to start")
            return

        while not self._stop.is_set():
            msg = self._consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                err = msg.error()
                if err.code() == KafkaError._PARTITION_EOF:
                    continue
                log.warning("kafka error: %s", err)
                continue
            value = msg.value()
            if value is None:
                continue
            # Block (briefly) if the asyncio queue is backed up — pushes
            # backpressure to Kafka rather than dropping events.
            future = asyncio.run_coroutine_threadsafe(self.queue.put((msg, value)), self.loop)
            try:
                future.result(timeout=30)
            except Exception:
                log.exception("failed to enqueue kafka message")

        try:
            self._consumer.close()
        except Exception:
            log.exception("error closing kafka consumer")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
async def process_loop(
    queue: asyncio.Queue,
    bridge: KafkaBridge,
    es: ESWriter,
    registry: DetectorRegistry,
    state_map: Dict[str, ServiceWindowState],
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        try:
            msg, raw = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue

        event = normaliser.parse(raw)
        if event is None:
            bridge.commit(msg)
            continue

        state = state_map.get(event.service)
        if state is None:
            state = ServiceWindowState(service=event.service)
            state_map[event.service] = state
            log.info("created window state for service %s", event.service)

        try:
            await es.write_log(event)
            anomalies = registry.run(event, state)
            for anomaly in anomalies:
                log.info(
                    "anomaly: service=%s type=%s severity=%s z=%.2f",
                    anomaly.service, anomaly.anomaly_type,
                    anomaly.severity, anomaly.z_score,
                )
                await es.write_anomaly(anomaly)
        except Exception:
            log.exception("processing failed for event from %s — skipping commit", event.service)
            continue

        bridge.commit(msg)


async def tick_loop(
    es: ESWriter,
    registry: DetectorRegistry,
    state_map: Dict[str, ServiceWindowState],
    stop: asyncio.Event,
) -> None:
    """Periodic scanner — flushes stale buckets so silence detection fires."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_INTERVAL_S)
        except asyncio.TimeoutError:
            pass
        for state in list(state_map.values()):
            try:
                anomalies = registry.run_tick(state)
                for anomaly in anomalies:
                    log.info(
                        "anomaly (tick): service=%s type=%s severity=%s",
                        anomaly.service, anomaly.anomaly_type, anomaly.severity,
                    )
                    await es.write_anomaly(anomaly)
            except Exception:
                log.exception("tick failed for service %s", state.service)


async def amain() -> None:
    log.info("collector starting (topic=%s, es=%s)", KAFKA_TOPIC, ES_URL)

    es_client = await connect_with_backoff(ES_URL)
    es = ESWriter(es_client)
    await es.bootstrap()

    registry = DetectorRegistry(build_detectors())
    state_map: Dict[str, ServiceWindowState] = {}

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=5000)
    bridge = KafkaBridge(
        loop=loop, queue=queue,
        topic=KAFKA_TOPIC, bootstrap=KAFKA_BOOTSTRAP, group=KAFKA_GROUP,
    )
    bridge.start()

    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    proc = asyncio.create_task(process_loop(queue, bridge, es, registry, state_map, stop))
    tick = asyncio.create_task(tick_loop(es, registry, state_map, stop))

    await stop.wait()
    log.info("shutdown signalled — draining")
    bridge.stop()
    for t in (proc, tick):
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
    await es.close()
    log.info("collector shut down cleanly")


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
