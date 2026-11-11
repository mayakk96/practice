"""PostgreSQL proofs for unique event claims and atomic projection version guards."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import func, select
from test_events_analytics import envelope

from app.analytics import AnalyticsService
from app.events import (
    ConsumedEvent,
    OutboxDispatcher,
    OutboxEvent,
    ProjectionConsumer,
    TransactionProjection,
    record_event,
)


def together(barrier, action):
    barrier.wait(timeout=10)
    return action()


@pytest.mark.postgres
def test_simultaneous_same_event_claim_commits_business_projection_once(postgres_factory):
    event = envelope()
    consumer = ProjectionConsumer(postgres_factory)
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(together, barrier, lambda: consumer.accept(event)) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert sorted(results) == [False, True]
    with postgres_factory() as session:
        assert session.scalar(select(func.count()).select_from(ConsumedEvent)) == 1
        assert session.scalar(select(func.count()).select_from(TransactionProjection)) == 1


@pytest.mark.postgres
def test_first_projection_race_and_concurrent_out_of_order_versions_preserve_newest(postgres_factory):
    newer = envelope(version=5, status="SETTLED", amount=50000)
    older = envelope(newer["aggregateId"], version=3, status="CAPTURED", amount=50000)
    consumer = ProjectionConsumer(postgres_factory)
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(together, barrier, lambda event=event: consumer.accept(event))
            for event in (newer, older)
        ]
        assert all(future.result(timeout=20) for future in futures)
    with postgres_factory() as session:
        row = session.get(TransactionProjection, UUID(newer["aggregateId"]))
        assert row.version == 5
        assert row.status == "SETTLED"
        assert session.scalar(select(func.count()).select_from(ConsumedEvent)) == 2
    daily = AnalyticsService(postgres_factory, events_enabled=True).daily()["items"][0]
    assert type(daily["volumeMinor"]) is int
    assert daily["volumeMinor"] == 50000
    assert daily["authorizationSuccessPercent"] == "100.00"


@pytest.mark.postgres
def test_two_dispatchers_share_db_lock_and_do_not_send_newer_before_predecessor(postgres_factory):
    event = envelope()
    aggregate = UUID(event["aggregateId"])
    with postgres_factory.begin() as session:
        record_event(session, "TransactionReceived", aggregate, event["payload"])
        record_event(
            session, "TransactionValidated", aggregate, envelope(version=1, status="VALIDATED")["payload"]
        )
    sent = []
    dispatcher = OutboxDispatcher(lambda key, value: sent.append(value), postgres_factory)
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(together, barrier, dispatcher.deliver_next) for _ in range(2)]
        for future in futures:
            future.result(timeout=20)
    while dispatcher.deliver_next():
        pass
    import json

    assert [json.loads(body)["eventType"] for body in sent] == ["TransactionReceived", "TransactionValidated"]
    with postgres_factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(OutboxEvent).where(OutboxEvent.published_at.is_(None))
            )
            == 0
        )
