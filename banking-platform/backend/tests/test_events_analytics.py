import copy
import json
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.analytics import AnalyticsService
from app.errors import DomainError
from app.events import (
    ConsumedEvent,
    InvalidEvent,
    OutboxDispatcher,
    OutboxEvent,
    ProjectionConsumer,
    TransactionProjection,
    metrics_text,
    record_event,
    utcnow,
)
from app.worker import process_record


def envelope(aggregate_id=None, *, version=0, status="RECEIVED", currency="USD", amount=100):
    return {
        "eventId": str(uuid4()),
        "eventType": "Transaction" + status.title(),
        "eventVersion": 1,
        "aggregateId": str(aggregate_id or uuid4()),
        "occurredAt": utcnow().isoformat(),
        "correlationId": "test-correlation",
        "payload": {
            "status": status,
            "transactionType": "CARD_PURCHASE",
            "amountMinor": amount,
            "currency": currency,
            "businessDate": "2026-11-08",
            "version": version,
        },
    }


def test_outbox_is_atomic_with_caller_transaction(factory):
    event = envelope()
    with pytest.raises(RuntimeError, match="abort business mutation"):
        with factory.begin() as session:
            record_event(session, event["eventType"], uuid4(), event["payload"])
            raise RuntimeError("abort business mutation")
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(OutboxEvent)) == 0
    with factory.begin() as session:
        record_event(session, event["eventType"], uuid4(), event["payload"], "safe-id")
    with factory() as session:
        row = session.scalar(select(OutboxEvent))
        assert json.loads(row.event_json)["correlationId"] == "safe-id"
        assert row.published_at is None


def test_duplicate_id_is_processed_once_and_reused_id_is_rejected(factory):
    consumer = ProjectionConsumer(factory)
    event = envelope()
    assert consumer.accept(event)
    assert consumer.accept(event) is False
    changed = copy.deepcopy(event)
    changed["payload"]["amountMinor"] = 200
    with pytest.raises(InvalidEvent, match="reused"):
        consumer.accept(changed)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ConsumedEvent)) == 1
        assert session.scalar(select(TransactionProjection.amount_minor)) == 100


def test_out_of_order_snapshots_never_regress_and_daily_currency_totals_are_separate(factory):
    consumer = ProjectionConsumer(factory)
    new = envelope(version=3, status="CAPTURED", amount=50000)
    old = envelope(new["aggregateId"], version=1, status="VALIDATED", amount=50000)
    consumer.accept(new)
    consumer.accept(old)
    consumer.accept(envelope(currency="EUR", amount=12000))
    analytics = AnalyticsService(factory, events_enabled=True)
    result = analytics.daily()
    assert result["source"] == "KAFKA_PROJECTION"
    assert result["total"] == 2
    assert [(item["currency"], item["volumeMinor"]) for item in result["items"]] == [
        ("EUR", 12000),
        ("USD", 50000),
    ]
    assert analytics.transactions(currency="USD")["items"][0]["status"] == "CAPTURED"
    assert analytics.daily(day=date(2026, 11, 8), currency="USD")["items"][0]["transactionCount"] == 1
    assert analytics.daily(page=1, size=1)["items"][0]["currency"] == "USD"
    with pytest.raises(DomainError):
        analytics.daily(currency="JPY")
    with pytest.raises(DomainError):
        analytics.daily(size=101)


def test_failed_predecessor_blocks_same_aggregate_but_not_other_aggregate(factory):
    first = uuid4()
    second = uuid4()
    with factory.begin() as session:
        record_event(session, "TransactionReceived", first, envelope()["payload"])
        record_event(
            session, "TransactionValidated", first, envelope(version=1, status="VALIDATED")["payload"]
        )
        record_event(session, "TransactionReceived", second, envelope()["payload"])
    sent = []
    fail = True

    def publisher(key, body):
        nonlocal fail
        if fail:
            fail = False
            raise TimeoutError("ambiguous acknowledgement")
        sent.append((key, json.loads(body)["eventType"]))

    dispatcher = OutboxDispatcher(publisher, factory)
    assert dispatcher.deliver_next()
    assert dispatcher.deliver_next()
    assert not dispatcher.deliver_next()
    assert sent == [(str(second), "TransactionReceived")]
    with factory.begin() as session:
        row = session.scalar(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == first).order_by(OutboxEvent.sequence)
        )
        assert row.attempts == 1
        row.available_at = utcnow() - timedelta(seconds=1)
    assert dispatcher.deliver_next()
    assert dispatcher.deliver_next()
    assert sent[-2:] == [(str(first), "TransactionReceived"), (str(first), "TransactionValidated")]
    assert b"banking_outbox_pending 0.0" in metrics_text(factory)
    assert b"banking_outbox_retry_count 1.0" in metrics_text(factory)


def test_metadata_allowlist_prevents_free_text_pii_events(factory):
    payload = {**envelope()["payload"], "customerName": "synthetic-but-not-allowed"}
    with pytest.raises(InvalidEvent):
        with factory.begin() as session:
            record_event(session, "TransactionReceived", uuid4(), payload)
    payload = {**envelope()["payload"], "amountMinor": 1.5}
    with pytest.raises(InvalidEvent):
        with factory.begin() as session:
            record_event(session, "TransactionReceived", uuid4(), payload)


def test_consumer_retry_and_dlt_require_acknowledgement_before_offset_commit():
    record = SimpleNamespace(value=b"{bad-json", key=b"key", topic="banking.events.v1", partition=1, offset=7)
    published = []
    service = SimpleNamespace(accept=lambda event: None)
    result = process_record(record, service, lambda *args: published.append(args), "banking.events.v1")
    assert result == "DEAD_LETTERED"
    assert published[0][0] == "banking.events.v1.DLT"
    assert ("source-offset", b"7") in published[0][3]
    event = envelope()
    record.value = json.dumps(event).encode()
    record.key = event["aggregateId"].encode()
    calls = []

    def unavailable(event):
        calls.append(event)
        raise ConnectionError("temporary database outage")

    service.accept = unavailable
    sleeps = []
    assert (
        process_record(
            record, service, lambda *args: published.append(args), "banking.events.v1", sleeps.append
        )
        == "DEAD_LETTERED"
    )
    assert len(calls) == 3
    assert sleeps == [0.1, 0.2]

    def broken_publisher(*args):
        raise TimeoutError("DLT unavailable")

    with pytest.raises(TimeoutError, match="DLT unavailable"):
        process_record(record, service, broken_publisher, "banking.events.v1", lambda _: None)


@pytest.mark.parametrize("amounts,expected", [((100, 101), 100), ((100, 103), 102)])
def test_average_minor_units_round_half_even_without_binary_money(factory, amounts, expected):
    consumer = ProjectionConsumer(factory)
    for amount in amounts:
        consumer.accept(envelope(amount=amount))
    day = AnalyticsService(factory, events_enabled=True).daily()["items"][0]
    assert day["averageAmountMinor"] == expected
    assert day["authorizationSuccessPercent"] is None
    assert type(day["volumeMinor"]) is int


def test_authorization_rates_exclude_pending_instructions(factory):
    consumer = ProjectionConsumer(factory)
    for status in ("AUTHORIZED", "DECLINED", "RECEIVED"):
        consumer.accept(envelope(status=status))
    day = AnalyticsService(factory, events_enabled=True).daily()["items"][0]
    assert day["transactionCount"] == 3
    assert day["authorizationDecisionCount"] == 2
    assert day["authorizationSuccessPercent"] == "50.00"
    assert day["declinePercent"] == "50.00"
