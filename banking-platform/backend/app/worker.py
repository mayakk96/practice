"""Run durable outbox dispatch and replay-safe analytics consumption.

Usage: EVENTS_ENABLED=true python -m app.worker
The API owns Alembic migration startup; Compose waits for its health check.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from datetime import UTC

from kafka import KafkaConsumer, KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError
from kafka.structs import OffsetAndMetadata
from prometheus_client import start_http_server

from .events import (
    DEAD_LETTERED,
    KAFKA_LAG,
    REGISTRY,
    InvalidEvent,
    OutboxDispatcher,
    ProjectionConsumer,
    refresh_metrics,
)

LOG = logging.getLogger(__name__)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        from datetime import datetime

        output = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name in ("eventId", "attempts", "failureClass"):
            if hasattr(record, name):
                output[name] = getattr(record, name)
        return json.dumps(output)


STOP = threading.Event()


def _topics(bootstrap, topic):
    admin = KafkaAdminClient(
        bootstrap_servers=bootstrap, client_id="banking-topic-setup", request_timeout_ms=10000
    )
    try:
        for name in (topic, topic + ".DLT"):
            try:
                admin.create_topics(
                    [NewTopic(name=name, num_partitions=3, replication_factor=1)], timeout_ms=10000
                )
            except TopicAlreadyExistsError:
                pass
    finally:
        admin.close()


def process_record(record, consumer_service, publisher, topic: str, sleeper=time.sleep) -> str:
    """Return only after the side effect or DLT acknowledgement is durable.

    The caller commits the exact next offset afterward. A crash at any point can
    replay the event and is covered by the event-ID database constraint.
    """
    failure = None
    for attempt in range(3):
        try:
            if record.value is None or len(record.value) > 16384:
                raise InvalidEvent("Unsupported event size")
            event = json.loads(record.value)
            if not isinstance(event, dict):
                raise InvalidEvent("Envelope must be an object")
            if record.key is None or record.key.decode("utf-8") != event.get("aggregateId"):
                raise InvalidEvent("Kafka key must equal aggregate ID")
            consumer_service.accept(event)
            return "PROCESSED"
        except (InvalidEvent, ValueError, UnicodeError) as exc:
            failure = type(exc).__name__
            break
        except Exception as exc:
            failure = type(exc).__name__
            if attempt < 2:
                sleeper(0.1 * (2**attempt))
    # Preserve bounded evidence with source offsets; never log the record body.
    value = (record.value or b"")[:65536]
    headers = [
        ("source-topic", record.topic.encode()),
        ("source-partition", str(record.partition).encode()),
        ("source-offset", str(record.offset).encode()),
        ("failure-class", failure.encode()),
        ("evidence-truncated", str(len(record.value or b"") > 65536).lower().encode()),
    ]
    publisher(topic + ".DLT", record.key, value, headers)
    DEAD_LETTERED.inc()
    return "DEAD_LETTERED"


def run():
    if os.getenv("EVENTS_ENABLED", "false").lower() != "true":
        raise SystemExit("Worker requires EVENTS_ENABLED=true")
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("kafka").setLevel(logging.WARNING)
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(",")
    topic = os.getenv("BANKING_EVENTS_TOPIC", "banking.events.v1")
    _topics(bootstrap, topic)
    producer = KafkaProducer(
        bootstrap_servers=bootstrap,
        acks="all",
        retries=0,
        max_block_ms=5000,
        request_timeout_ms=5000,
        client_id="banking-outbox",
    )
    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=bootstrap,
        group_id=os.getenv("BANKING_CONSUMER_GROUP", "banking-analytics-v1"),
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        max_poll_records=20,
        request_timeout_ms=30000,
        session_timeout_ms=10000,
        client_id="banking-analytics",
    )

    def publish(key, body):
        producer.send(topic, key=key.encode(), value=body).get(timeout=6)

    def dead_letter(destination, key, body, headers):
        producer.send(destination, key=key, value=body, headers=headers).get(timeout=6)

    dispatcher = OutboxDispatcher(publish)
    projector = ProjectionConsumer()
    start_http_server(int(os.getenv("WORKER_METRICS_PORT", "9095")), addr="0.0.0.0", registry=REGISTRY)
    for name in (signal.SIGTERM, signal.SIGINT):
        signal.signal(name, lambda *_: STOP.set())
    try:
        while not STOP.is_set():
            for _ in range(20):
                if STOP.is_set() or not dispatcher.deliver_next():
                    break
            for partition, records in consumer.poll(timeout_ms=500).items():
                for record in records:
                    process_record(record, projector, dead_letter, topic)
                    consumer.commit({partition: OffsetAndMetadata(record.offset + 1, "", -1)})
                    if STOP.is_set():
                        break
            refresh_metrics()
            assigned = consumer.assignment()
            if assigned:
                try:
                    end_offsets = consumer.end_offsets(assigned)
                    committed = {partition: consumer.committed(partition) for partition in assigned}
                    never_committed = [partition for partition, offset in committed.items() if offset is None]
                    beginnings = consumer.beginning_offsets(never_committed) if never_committed else {}
                    KAFKA_LAG.set(
                        sum(
                            max(
                                0,
                                end_offsets[p]
                                - (committed[p] if committed[p] is not None else beginnings[p]),
                            )
                            for p in assigned
                        )
                    )
                except Exception as exc:
                    KAFKA_LAG.set(-1)
                    LOG.warning(
                        "consumer_lag_measurement_unavailable", extra={"failureClass": type(exc).__name__}
                    )
    finally:
        consumer.close(autocommit=False)
        producer.close(timeout=10)


if __name__ == "__main__":
    run()
