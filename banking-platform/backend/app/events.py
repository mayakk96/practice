"""Versioned metadata events, transactional outbox and replay-safe read projections.

No function commits a caller's banking transaction. Broker acknowledgement and an
outbox update cannot be atomic, so consumers deliberately tolerate redelivery.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from . import db
from .db import Base

UTC = UTC
LOG = logging.getLogger(__name__)
TRANSACTION_EVENTS = frozenset(
    "Transaction" + name
    for name in (
        "Received",
        "Validated",
        "Authorized",
        "Declined",
        "Captured",
        "Cleared",
        "Settled",
        "Reversed",
        "Refunded",
    )
)
SETTLEMENT_EVENTS = frozenset(
    (
        "SettlementBatchCreated",
        "SettlementBatchReady",
        "SettlementBatchSubmitted",
        "SettlementConfirmed",
        "SettlementReconciled",
    )
)
EXCEPTION_EVENTS = frozenset(("OperationalExceptionCreated", "OperationalExceptionUpdated"))
RECONCILIATION_EVENTS = frozenset(("ReconciliationCompleted", "ReconciliationMismatchDetected"))
EVENT_TYPES = TRANSACTION_EVENTS | SETTLEMENT_EVENTS | EXCEPTION_EVENTS | RECONCILIATION_EVENTS
PAYLOAD_KEYS = frozenset(
    (
        "status",
        "transactionType",
        "amountMinor",
        "currency",
        "businessDate",
        "version",
        "transactionCount",
        "grossDebitMinor",
        "grossCreditMinor",
        "netSettlementMinor",
        "matched",
        "unmatched",
        "varianceMinor",
        "category",
        "severity",
        "transactionId",
        "reconciliationRunId",
        "totalInternalMinor",
        "totalExternalMinor",
    )
)


class InvalidEvent(ValueError):
    """Permanent envelope/schema failure; safe for immediate dead-letter handling."""


class OutboxEvent(Base):
    __tablename__ = "banking_outbox"
    sequence: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True, nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    event_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_failure: Mapped[str | None] = mapped_column(String(60))
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_banking_outbox_attempts"),
        Index("ix_banking_outbox_pending", "published_at", "available_at", "sequence"),
        Index("ix_banking_outbox_order", "aggregate_id", "published_at", "sequence"),
    )


class ConsumedEvent(Base):
    __tablename__ = "banking_consumed_event"
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    envelope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TransactionProjection(Base):
    __tablename__ = "banking_transaction_projection"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint(
            "amount_minor > 0 AND amount_minor <= 1000000000000", name="ck_banking_projection_money"
        ),
        CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_banking_projection_currency"),
        CheckConstraint("version >= 0", name="ck_banking_projection_version"),
        Index("ix_banking_projection_daily", "business_date", "currency", "status"),
    )


class SettlementProjection(Base):
    __tablename__ = "banking_settlement_projection"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    gross_debit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gross_credit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_banking_settlement_projection_currency"),
        CheckConstraint(
            "transaction_count > 0 AND gross_debit_minor >= 0 AND gross_credit_minor >= 0",
            name="ck_banking_settlement_projection_totals",
        ),
        CheckConstraint(
            "net_minor = gross_debit_minor - gross_credit_minor", name="ck_banking_settlement_projection_net"
        ),
        CheckConstraint("version >= 0", name="ck_banking_settlement_projection_version"),
        Index("ix_banking_settlement_projection_date", "business_date", "currency"),
    )


class ExceptionProjection(Base):
    __tablename__ = "banking_exception_projection"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN','INVESTIGATING','RESOLVED')", name="ck_banking_exception_projection_status"
        ),
        CheckConstraint("version >= 0", name="ck_banking_exception_projection_version"),
        Index("ix_banking_exception_projection_status", "status", "severity"),
    )


class ReconciliationProjection(Base):
    __tablename__ = "banking_reconciliation_projection"
    __table_args__ = (
        CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_banking_recon_projection_currency"),
        CheckConstraint(
            "matched >= 0 AND unmatched >= 0 AND version >= 0", name="ck_banking_recon_projection_counts"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    matched: Mapped[int] = mapped_column(Integer, nullable=False)
    unmatched: Mapped[int] = mapped_column(Integer, nullable=False)
    variance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def utcnow() -> datetime:
    return datetime.now(UTC)


def validate_event(event: dict[str, Any]) -> dict[str, Any]:
    try:
        if set(event) != {
            "eventId",
            "eventType",
            "eventVersion",
            "aggregateId",
            "occurredAt",
            "correlationId",
            "payload",
        }:
            raise InvalidEvent("Unsupported envelope fields")
        uuid.UUID(str(event["eventId"]))
        uuid.UUID(str(event["aggregateId"]))
        occurred = datetime.fromisoformat(event["occurredAt"].replace("Z", "+00:00"))
        if (
            occurred.tzinfo is None
            or (type(event["eventVersion"]) is not int or event["eventVersion"] != 1)
            or event["eventType"] not in EVENT_TYPES
        ):
            raise InvalidEvent("Unsupported event version, type or timestamp")
        correlation = event["correlationId"]
        if (
            not isinstance(correlation, str)
            or not 1 <= len(correlation) <= 64
            or not all(c.isalnum() or c in "_-" for c in correlation)
        ):
            raise InvalidEvent("Invalid correlation metadata")
        payload = event["payload"]
        if not isinstance(payload, dict) or not set(payload).issubset(PAYLOAD_KEYS):
            raise InvalidEvent("Unsupported payload metadata")
        for key, value in payload.items():
            if key.endswith("Minor") or key in {"version", "transactionCount", "matched", "unmatched"}:
                if type(value) is not int or abs(value) > 9_223_372_036_854_775_807:
                    raise InvalidEvent("Invalid integer metadata")
            elif key in {"transactionId", "reconciliationRunId"}:
                uuid.UUID(str(value))
            elif key == "businessDate":
                date.fromisoformat(value)
            elif key == "currency":
                if value not in {"USD", "EUR", "GBP"}:
                    raise InvalidEvent("Unsupported currency")
            elif (
                not isinstance(value, str)
                or not 1 <= len(value) <= 40
                or not all(c.isupper() or c.isdigit() or c == "_" for c in value)
            ):
                raise InvalidEvent("Invalid enum metadata")
        if any(payload.get(key, 0) < 0 for key in ("version", "transactionCount", "matched", "unmatched")):
            raise InvalidEvent("Invalid aggregate version or count")
        required = set()
        if event["eventType"] in TRANSACTION_EVENTS:
            required = {"status", "transactionType", "amountMinor", "currency", "businessDate", "version"}
            if payload.get("status") not in {
                "RECEIVED",
                "VALIDATED",
                "AUTHORIZED",
                "DECLINED",
                "CAPTURED",
                "CLEARED",
                "SETTLED",
                "REVERSED",
                "REFUNDED",
            }:
                raise InvalidEvent("Unsupported transaction status")
            if "Transaction" + payload["status"].title() != event["eventType"]:
                raise InvalidEvent("Event type and status disagree")
            if (
                payload.get("transactionType") not in {"CARD_PURCHASE", "ACCOUNT_TRANSFER", "REFUND"}
                or not 0 < payload.get("amountMinor", 0) <= 1_000_000_000_000
            ):
                raise InvalidEvent("Invalid transaction metadata")
        elif event["eventType"] in SETTLEMENT_EVENTS:
            if payload.get("status") not in {"OPEN", "READY", "SUBMITTED", "CONFIRMED", "RECONCILED"}:
                raise InvalidEvent("Unsupported settlement status")
            if payload.get("transactionCount", 0) <= 0 or any(
                payload.get(key, -1) < 0 for key in ("grossDebitMinor", "grossCreditMinor")
            ):
                raise InvalidEvent("Invalid settlement totals")
            if payload.get("netSettlementMinor") != payload.get("grossDebitMinor", 0) - payload.get(
                "grossCreditMinor", 0
            ):
                raise InvalidEvent("Settlement totals disagree")
            required = {
                "status",
                "currency",
                "businessDate",
                "transactionCount",
                "grossDebitMinor",
                "grossCreditMinor",
                "netSettlementMinor",
                "version",
            }
        elif event["eventType"] in EXCEPTION_EVENTS:
            if payload.get("status") not in {"OPEN", "INVESTIGATING", "RESOLVED"}:
                raise InvalidEvent("Unsupported exception status")
            required = {"status", "category", "severity", "version"}
        elif event["eventType"] == "ReconciliationCompleted":
            required = {"businessDate", "currency", "matched", "unmatched", "varianceMinor", "status"}
        if not required.issubset(payload):
            raise InvalidEvent("Missing event metadata")
        if len(json.dumps(event, separators=(",", ":"))) > 16_384:
            raise InvalidEvent("Event exceeds size limit")
        return event
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        if isinstance(exc, InvalidEvent):
            raise
        raise InvalidEvent("Malformed event metadata") from None


def record_event(
    session,
    event_type: str,
    aggregate_id: uuid.UUID,
    payload: dict[str, Any],
    correlation_id: str | None = None,
) -> OutboxEvent:
    """Append to the caller's transaction; never perform network I/O here."""
    if not session.in_transaction():
        raise RuntimeError("record_event requires an active banking transaction")
    now = utcnow()
    event_id = uuid.uuid4()
    if correlation_id is None:
        from .common import correlation_id as current_correlation_id

        correlation_id = current_correlation_id()
    payload = {
        key: str(value) if isinstance(value, (uuid.UUID, date)) else value for key, value in payload.items()
    }
    envelope = validate_event(
        {
            "eventId": str(event_id),
            "eventType": event_type,
            "eventVersion": 1,
            "aggregateId": str(aggregate_id),
            "occurredAt": now.isoformat(),
            "correlationId": correlation_id or str(event_id),
            "payload": payload,
        }
    )
    row = OutboxEvent(
        id=event_id,
        aggregate_id=aggregate_id,
        event_type=event_type,
        event_json=json.dumps(envelope, sort_keys=True, separators=(",", ":")),
        created_at=now,
        available_at=now,
        attempts=0,
    )
    session.add(row)
    return row


# Each process exposes its own delivery counters; database gauges are shared.
REGISTRY = CollectorRegistry()
PUBLISHED = Counter(
    "banking_outbox_delivered_total", "Broker acknowledgements durably recorded", registry=REGISTRY
)
FAILURES = Counter("banking_outbox_failures_total", "Failed publication attempts", registry=REGISTRY)
REDELIVERED = Counter("banking_consumer_duplicates_total", "Identical event IDs ignored", registry=REGISTRY)
CONSUMED = Counter("banking_consumer_processed_total", "Committed new event IDs", registry=REGISTRY)
DELIVERY = Histogram(
    "banking_projection_delivery_seconds", "Event creation to committed projection latency", registry=REGISTRY
)
STALE = Counter("banking_consumer_stale_snapshots_total", "Older snapshots ignored", registry=REGISTRY)
DEAD_LETTERED = Counter(
    "banking_consumer_dead_letter_total", "Records acknowledged after DLT publication", registry=REGISTRY
)
KAFKA_LAG = Gauge(
    "banking_kafka_consumer_lag",
    "End offset minus committed offset for this worker assigned partitions; -1 means unknown",
    registry=REGISTRY,
)
KAFKA_LAG.set(-1)
PENDING = Gauge("banking_outbox_pending", "Unpublished banking events", registry=REGISTRY)
OLDEST = Gauge("banking_outbox_oldest_pending_seconds", "Age of oldest unpublished event", registry=REGISTRY)
RETRIES = Gauge("banking_outbox_retry_count", "Persisted failed outbox attempts", registry=REGISTRY)


def refresh_metrics(factory=None) -> None:
    factory = factory or db.SessionLocal
    with factory() as session:
        pending, oldest = session.execute(
            select(func.count(), func.min(OutboxEvent.created_at)).where(OutboxEvent.published_at.is_(None))
        ).one()
        retries = session.scalar(select(func.coalesce(func.sum(OutboxEvent.attempts), 0)))
    PENDING.set(pending)
    if oldest is not None and oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=UTC)
    OLDEST.set(max(0, (utcnow() - oldest).total_seconds()) if oldest else 0)
    RETRIES.set(retries)


def metrics_text(factory=None) -> bytes:
    refresh_metrics(factory)
    return generate_latest(REGISTRY)


class OutboxDispatcher:
    """One locked row and bounded acknowledgement wait per database transaction."""

    def __init__(self, publisher: Callable[[str, bytes], None], factory=None):
        self.factory = factory or db.SessionLocal
        self.publisher = publisher

    def deliver_next(self) -> bool:
        failed = False
        with self.factory.begin() as session:
            older = OutboxEvent.__table__.alias("older")
            predecessor = (
                select(older.c.sequence)
                .where(
                    older.c.aggregate_id == OutboxEvent.aggregate_id,
                    older.c.published_at.is_(None),
                    older.c.sequence < OutboxEvent.sequence,
                )
                .exists()
            )
            row = session.scalar(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None), OutboxEvent.available_at <= utcnow(), ~predecessor)
                .order_by(OutboxEvent.sequence)
                .limit(1)
                .with_for_update()
            )
            if row is None:
                return False
            try:
                self.publisher(str(row.aggregate_id), row.event_json.encode())
                row.published_at = utcnow()
                row.last_failure = None
            except Exception as exc:
                # An acknowledgement timeout is ambiguous; retain the same event ID.
                failed = True
                row.attempts += 1
                row.available_at = utcnow() + timedelta(seconds=min(60, 2 ** min(row.attempts - 1, 6)))
                row.last_failure = type(exc).__name__[:60]
                LOG.warning(
                    "banking_event_publish_failed", extra={"eventId": str(row.id), "attempts": row.attempts}
                )
        (FAILURES if failed else PUBLISHED).inc()
        return True


class ProjectionConsumer:
    def __init__(self, factory=None):
        self.factory = factory or db.SessionLocal

    def accept(self, event: dict[str, Any]) -> bool:
        event = validate_event(event)
        fingerprint = hashlib.sha256(
            json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        event_id = uuid.UUID(event["eventId"])
        aggregate_id = uuid.UUID(event["aggregateId"])
        for attempt in range(3):
            try:
                with self.factory.begin() as session:
                    existing = session.get(ConsumedEvent, event_id)
                    if existing:
                        self._require_same(existing.envelope_hash, fingerprint)
                        REDELIVERED.inc()
                        return False
                    session.add(
                        ConsumedEvent(
                            event_id=event_id,
                            aggregate_id=aggregate_id,
                            event_type=event["eventType"],
                            envelope_hash=fingerprint,
                            received_at=utcnow(),
                        )
                    )
                    session.flush()
                    stale = self._project(session, event, aggregate_id)
                CONSUMED.inc()
                occurred = datetime.fromisoformat(event["occurredAt"].replace("Z", "+00:00"))
                DELIVERY.observe(max(0, (utcnow() - occurred).total_seconds()))
                if stale:
                    STALE.inc()
                return True
            except IntegrityError:
                # PostgreSQL's failed transaction has ended before any winner lookup.
                with self.factory() as session:
                    winner = session.get(ConsumedEvent, event_id)
                    if winner:
                        self._require_same(winner.envelope_hash, fingerprint)
                        REDELIVERED.inc()
                        return False
                # A different event may have inserted this aggregate's first snapshot.
                if attempt == 2:
                    raise
        raise RuntimeError("Unreachable consumer retry")

    @staticmethod
    def _require_same(existing_hash: str, fingerprint: str) -> None:
        if existing_hash != fingerprint:
            raise InvalidEvent("An event ID was reused with different content")

    @staticmethod
    def _project(session, event: dict[str, Any], aggregate_id: uuid.UUID) -> bool:
        payload = event["payload"]
        event_type = event["eventType"]
        version = payload.get("version", 0)
        common = {
            "version": version,
            "updated_at": datetime.fromisoformat(event["occurredAt"].replace("Z", "+00:00")),
        }
        if event_type in TRANSACTION_EVENTS:
            model = TransactionProjection
            values = {
                **common,
                "status": payload["status"],
                "transaction_type": payload["transactionType"],
                "amount_minor": payload["amountMinor"],
                "currency": payload["currency"],
                "business_date": date.fromisoformat(payload["businessDate"]),
            }
        elif event_type in SETTLEMENT_EVENTS:
            model = SettlementProjection
            values = {
                **common,
                "status": payload["status"],
                "currency": payload["currency"],
                "business_date": date.fromisoformat(payload["businessDate"]),
                "transaction_count": payload["transactionCount"],
                "gross_debit_minor": payload["grossDebitMinor"],
                "gross_credit_minor": payload["grossCreditMinor"],
                "net_minor": payload["netSettlementMinor"],
            }
        elif event_type in EXCEPTION_EVENTS:
            model = ExceptionProjection
            values = {
                **common,
                "status": payload["status"],
                "category": payload["category"],
                "severity": payload["severity"],
            }
        elif event_type == "ReconciliationCompleted":
            model = ReconciliationProjection
            values = {
                **common,
                "business_date": date.fromisoformat(payload["businessDate"]),
                "currency": payload["currency"],
                "matched": payload["matched"],
                "unmatched": payload["unmatched"],
                "variance_minor": payload["varianceMinor"],
            }
        else:
            return False  # Mismatch detail events are audited, not added to financial totals.
        existing = session.get(model, aggregate_id)
        if existing is None:
            session.add(model(id=aggregate_id, **values))
            session.flush()
            return False
        # Database predicate protects against regression even if deliveries race.
        result = session.execute(
            update(model).where(model.id == aggregate_id, model.version < version).values(**values)
        )
        return result.rowcount == 0
