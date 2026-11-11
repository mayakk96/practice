"""Optional real broker test; local unit builds do not require Kafka."""

import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from kafka import KafkaConsumer, KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic
from sqlalchemy import func, select

from app.events import ConsumedEvent, ProjectionConsumer, TransactionProjection
from app.worker import process_record


@pytest.mark.kafka
def test_real_broker_duplicate_delivery_and_dlt_preserve_single_projection(factory):
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if not bootstrap:
        pytest.skip("Set KAFKA_BOOTSTRAP_SERVERS to run real broker tests")
    topic = "banking-test-" + uuid4().hex
    bootstrap = bootstrap.split(",")
    admin = KafkaAdminClient(bootstrap_servers=bootstrap, request_timeout_ms=10000)
    producer = KafkaProducer(bootstrap_servers=bootstrap, acks="all", request_timeout_ms=10000)
    consumer = None
    dead_consumer = None
    try:
        admin.create_topics([NewTopic(topic, 1, 1), NewTopic(topic + ".DLT", 1, 1)])
        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=bootstrap,
            group_id=topic,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            consumer_timeout_ms=15000,
        )
        event = {
            "eventId": str(uuid4()),
            "eventType": "TransactionCaptured",
            "eventVersion": 1,
            "aggregateId": str(uuid4()),
            "occurredAt": datetime.now(UTC).isoformat(),
            "correlationId": "broker-test",
            "payload": {
                "status": "CAPTURED",
                "transactionType": "CARD_PURCHASE",
                "amountMinor": 50000,
                "currency": "USD",
                "businessDate": "2026-11-08",
                "version": 3,
            },
        }
        body = json.dumps(event).encode()
        for value in (body, body, b"{malformed"):
            producer.send(topic, key=event["aggregateId"].encode(), value=value).get(timeout=10)
        service = ProjectionConsumer(factory)
        outcomes = []

        def dlt(destination, key, value, headers):
            producer.send(destination, key=key, value=value, headers=headers).get(timeout=10)

        for record in consumer:
            outcomes.append(process_record(record, service, dlt, topic))
            if len(outcomes) == 3:
                break
        assert outcomes == ["PROCESSED", "PROCESSED", "DEAD_LETTERED"]
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(ConsumedEvent)) == 1
            assert session.scalar(select(func.count()).select_from(TransactionProjection)) == 1
        dead_consumer = KafkaConsumer(
            topic + ".DLT",
            bootstrap_servers=bootstrap,
            group_id=topic + "-dlt",
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            consumer_timeout_ms=15000,
        )
        dead_letter = next(iter(dead_consumer))
        assert dead_letter.value == b"{malformed"
        assert ("source-offset", b"2") in dead_letter.headers
    finally:
        if consumer:
            consumer.close()
        if dead_consumer:
            dead_consumer.close()
        producer.close()
        admin.delete_topics([topic, topic + ".DLT"], timeout_ms=10000)
        admin.close()
