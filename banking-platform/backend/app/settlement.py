"""Currency-scoped, auditable settlement batches with database concurrency controls."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    exists,
    func,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from . import db
from .common import actor, correlation_id, json_value, now, page_result, validate_page
from .db import Base
from .errors import DomainError


class SettlementBatch(Base):
    __tablename__ = "settlement_batch"
    __table_args__ = (
        Index("ix_settlement_status_date", "status", "business_date", "id"),
        CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_settlement_currency"),
        CheckConstraint(
            "status IN ('OPEN','READY','SUBMITTED','CONFIRMED','RECONCILED')", name="ck_settlement_status"
        ),
        CheckConstraint("transaction_count > 0 AND transaction_count <= 1000", name="ck_settlement_count"),
        CheckConstraint("gross_debit_minor >= 0 AND gross_credit_minor >= 0", name="ck_settlement_gross"),
        CheckConstraint("net_minor = gross_debit_minor - gross_credit_minor", name="ck_settlement_net"),
        CheckConstraint("version >= 0", name="ck_settlement_version"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    transaction_count: Mapped[int] = mapped_column(Integer)
    gross_debit_minor: Mapped[int] = mapped_column(BigInteger)
    gross_credit_minor: Mapped[int] = mapped_column(BigInteger)
    net_minor: Mapped[int] = mapped_column(BigInteger)
    version: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SettlementItem(Base):
    __tablename__ = "settlement_item"
    __table_args__ = (
        Index("ix_settlement_items_batch", "batch_id", "id"),
        CheckConstraint(
            "amount_minor > 0 AND amount_minor <= 1000000000000", name="ck_settlement_item_amount"
        ),
        CheckConstraint("direction IN ('DEBIT','CREDIT')", name="ck_settlement_item_direction"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("settlement_batch.id"))
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("financial_transaction.id"), unique=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    direction: Mapped[str] = mapped_column(String(10))


class SettlementHistory(Base):
    __tablename__ = "settlement_history"
    __table_args__ = (UniqueConstraint("batch_id", "batch_version", name="uq_settlement_history_version"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("settlement_batch.id"))
    previous_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(500))
    actor: Mapped[str] = mapped_column(String(100))
    correlation_id: Mapped[str] = mapped_column(String(100))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    batch_version: Mapped[int] = mapped_column(BigInteger)


class CreateSettlementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    business_date: date = Field(alias="businessDate")
    currency: Annotated[str, Field(pattern=r"^(USD|EUR|GBP)$")]
    max_items: Annotated[int, Field(strict=True, ge=1, le=1000, alias="maxItems")] = 100


class SettlementCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    expected_version: Annotated[int, Field(strict=True, ge=0, alias="expectedVersion")]
    reason: Annotated[str, Field(min_length=1, max_length=500)]


def batch_view(row: SettlementBatch) -> dict:
    return {
        "id": str(row.id),
        "businessDate": row.business_date.isoformat(),
        "currency": row.currency,
        "status": row.status,
        "transactionCount": row.transaction_count,
        "grossDebitMinor": row.gross_debit_minor,
        "grossCreditMinor": row.gross_credit_minor,
        "netSettlementMinor": row.net_minor,
        "version": row.version,
        "createdAt": json_value(row.created_at),
        "updatedAt": json_value(row.updated_at),
    }


def _event(session, batch, event_type):
    from .events import record_event

    record_event(
        session,
        event_type,
        batch.id,
        {
            "status": batch.status,
            "currency": batch.currency,
            "businessDate": batch.business_date.isoformat(),
            "transactionCount": batch.transaction_count,
            "grossDebitMinor": batch.gross_debit_minor,
            "grossCreditMinor": batch.gross_credit_minor,
            "netSettlementMinor": batch.net_minor,
            "version": batch.version,
        },
    )


def _history(session, batch, previous, reason):
    session.add(
        SettlementHistory(
            batch_id=batch.id,
            previous_status=previous,
            new_status=batch.status,
            reason=reason,
            actor=actor()[:100],
            correlation_id=correlation_id()[:100],
            batch_version=batch.version,
        )
    )


def _change(session, batch, expected_version, expected_status, target_status, reason, event_type):
    if batch.version != expected_version:
        raise DomainError(409, "Settlement batch changed concurrently; reload its version.")
    if batch.status != expected_status:
        raise DomainError(409, f"Settlement transition requires {expected_status} status.")
    if not reason or not reason.strip() or len(reason) > 500:
        raise DomainError(400, "A nonblank reason of at most 500 characters is required.")
    previous = batch.status
    changed = session.execute(
        update(SettlementBatch)
        .where(
            SettlementBatch.id == batch.id,
            SettlementBatch.version == expected_version,
            SettlementBatch.status == expected_status,
        )
        .values(status=target_status, version=expected_version + 1, updated_at=now()),
        execution_options={"synchronize_session": False},
    )
    if changed.rowcount != 1:
        raise DomainError(409, "Settlement batch changed concurrently; reload its version.")
    session.refresh(batch)
    _history(session, batch, previous, reason.strip())
    _event(session, batch, event_type)
    session.flush()


def get_batch_locked(session, batch_id):
    batch = session.scalar(
        select(SettlementBatch).where(SettlementBatch.id == UUID(str(batch_id))).with_for_update()
    )
    if batch is None:
        raise DomainError(404, "Settlement batch was not found.")
    return batch


def reconcile_in_session(session, batch, expected_version, reason):
    """Internal only. Reconciliation calls this after proving every batch item matches its run."""
    _change(session, batch, expected_version, "CONFIRMED", "RECONCILED", reason, "SettlementReconciled")
    return batch_view(batch)


class SettlementService:
    def __init__(self, factory=None):
        self.factory = factory or db.SessionLocal

    def create(self, body: CreateSettlementRequest | dict) -> dict:
        from .models import FinancialTransaction

        request = (
            body
            if isinstance(body, CreateSettlementRequest)
            else CreateSettlementRequest.model_validate(body)
        )
        try:
            with self.factory.begin() as session:
                query = (
                    select(FinancialTransaction)
                    .where(
                        FinancialTransaction.status == "CLEARED",
                        FinancialTransaction.business_date == request.business_date,
                        FinancialTransaction.currency == request.currency,
                        ~exists().where(SettlementItem.transaction_id == FinancialTransaction.id),
                    )
                    .order_by(FinancialTransaction.id)
                    .limit(request.max_items)
                    .with_for_update(skip_locked=True)
                )
                transactions = session.scalars(query).all()
                if not transactions:
                    raise DomainError(
                        409, "No unassigned cleared transactions are available for this date and currency."
                    )
                debit = sum(t.amount_minor for t in transactions if t.transaction_type != "REFUND")
                credit = sum(t.amount_minor for t in transactions if t.transaction_type == "REFUND")
                batch = SettlementBatch(
                    business_date=request.business_date,
                    currency=request.currency,
                    transaction_count=len(transactions),
                    gross_debit_minor=debit,
                    gross_credit_minor=credit,
                    net_minor=debit - credit,
                )
                session.add(batch)
                session.flush()
                for transaction in transactions:
                    session.add(
                        SettlementItem(
                            batch_id=batch.id,
                            transaction_id=transaction.id,
                            amount_minor=transaction.amount_minor,
                            direction="CREDIT" if transaction.transaction_type == "REFUND" else "DEBIT",
                        )
                    )
                _history(session, batch, None, "Batch formed from eligible cleared transactions")
                _event(session, batch, "SettlementBatchCreated")
                session.flush()
                return batch_view(batch)
        except IntegrityError:
            raise DomainError(
                409, "Concurrent settlement assignment conflict; retry batch creation."
            ) from None

    def get(self, batch_id: UUID) -> dict:
        with self.factory() as session:
            batch = session.get(SettlementBatch, UUID(str(batch_id)))
            if batch is None:
                raise DomainError(404, "Settlement batch was not found.")
            return batch_view(batch)

    def list(self, page=0, size=20, status=None) -> dict:
        validate_page(page, size)
        if status is not None and status not in {"OPEN", "READY", "SUBMITTED", "CONFIRMED", "RECONCILED"}:
            raise DomainError(400, "Unsupported settlement status.")
        with self.factory() as session:
            query = select(SettlementBatch)
            if status:
                query = query.where(SettlementBatch.status == status)
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            batches = session.scalars(
                query.order_by(SettlementBatch.created_at, SettlementBatch.id).offset(page * size).limit(size)
            ).all()
            return page_result([batch_view(batch) for batch in batches], page, size, total)

    def _command(self, batch_id, body, action):
        from .transactions import get_transaction_locked, ledger_settle, transition

        request = body if isinstance(body, SettlementCommand) else SettlementCommand.model_validate(body)
        states = {
            "ready": ("OPEN", "READY", "SettlementBatchReady"),
            "submit": ("READY", "SUBMITTED", "SettlementBatchSubmitted"),
            "confirm": ("SUBMITTED", "CONFIRMED", "SettlementConfirmed"),
        }
        expected, target, event_type = states[action]
        with self.factory.begin() as session:
            batch = get_batch_locked(session, batch_id)
            if batch.version != request.expected_version or batch.status != expected:
                raise DomainError(
                    409, "Settlement status or version changed; reload before applying this command."
                )
            items = session.scalars(
                select(SettlementItem)
                .where(SettlementItem.batch_id == batch.id)
                .order_by(SettlementItem.transaction_id)
            ).all()
            if len(items) != batch.transaction_count:
                raise DomainError(409, "Settlement item count does not match its immutable batch summary.")
            debit = sum(item.amount_minor for item in items if item.direction == "DEBIT")
            credit = sum(item.amount_minor for item in items if item.direction == "CREDIT")
            if (debit, credit, debit - credit) != (
                batch.gross_debit_minor,
                batch.gross_credit_minor,
                batch.net_minor,
            ):
                raise DomainError(409, "Settlement items do not match batch financial totals.")
            for item in items:
                transaction = get_transaction_locked(session, item.transaction_id)
                direction = "CREDIT" if transaction.transaction_type == "REFUND" else "DEBIT"
                if (
                    transaction.status,
                    transaction.amount_minor,
                    transaction.currency,
                    transaction.business_date,
                    direction,
                ) != ("CLEARED", item.amount_minor, batch.currency, batch.business_date, item.direction):
                    raise DomainError(
                        409, "A settlement transaction is no longer eligible or has inconsistent details."
                    )
                if action == "confirm":
                    transition(session, transaction, "SETTLED", "Settlement confirmation recorded")
                    ledger_settle(session, transaction)
            _change(session, batch, request.expected_version, expected, target, request.reason, event_type)
            return batch_view(batch)

    def ready(self, batch_id, body):
        return self._command(batch_id, body, "ready")

    def submit(self, batch_id, body):
        return self._command(batch_id, body, "submit")

    def confirm(self, batch_id, body):
        return self._command(batch_id, body, "confirm")

    def items(self, batch_id, page=0, size=20):
        validate_page(page, size)
        with self.factory() as session:
            if session.get(SettlementBatch, UUID(str(batch_id))) is None:
                raise DomainError(404, "Settlement batch was not found.")
            query = select(SettlementItem).where(SettlementItem.batch_id == UUID(str(batch_id)))
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            rows = session.scalars(
                query.order_by(SettlementItem.transaction_id).offset(page * size).limit(size)
            ).all()
            return page_result(
                [
                    {
                        "id": str(row.id),
                        "transactionId": str(row.transaction_id),
                        "amountMinor": row.amount_minor,
                        "direction": row.direction,
                    }
                    for row in rows
                ],
                page,
                size,
                total,
            )

    def history(self, batch_id, page=0, size=20):
        validate_page(page, size)
        with self.factory() as session:
            if session.get(SettlementBatch, UUID(str(batch_id))) is None:
                raise DomainError(404, "Settlement batch was not found.")
            query = select(SettlementHistory).where(SettlementHistory.batch_id == UUID(str(batch_id)))
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            rows = session.scalars(
                query.order_by(SettlementHistory.batch_version).offset(page * size).limit(size)
            ).all()
            return page_result(
                [
                    {
                        "previousStatus": row.previous_status,
                        "newStatus": row.new_status,
                        "reason": row.reason,
                        "actor": row.actor,
                        "correlationId": row.correlation_id,
                        "changedAt": json_value(row.changed_at),
                        "version": row.batch_version,
                    }
                    for row in rows
                ],
                page,
                size,
                total,
            )


router = APIRouter(prefix="/api/settlements", tags=["settlement"])


@router.post("", status_code=201)
def create_batch(body: CreateSettlementRequest):
    return SettlementService().create(body)


@router.get("")
def list_batches(page: int = 0, size: int = 20, status: str | None = None):
    return SettlementService().list(page, size, status)


@router.get("/{batch_id}")
def get_batch(batch_id: UUID):
    return SettlementService().get(batch_id)


@router.get("/{batch_id}/items")
def get_batch_items(batch_id: UUID, page: int = 0, size: int = 20):
    return SettlementService().items(batch_id, page, size)


@router.get("/{batch_id}/history")
def get_batch_history(batch_id: UUID, page: int = 0, size: int = 20):
    return SettlementService().history(batch_id, page, size)


@router.post("/{batch_id}/ready")
def ready_batch(batch_id: UUID, body: SettlementCommand):
    return SettlementService().ready(batch_id, body)


@router.post("/{batch_id}/submit")
def submit_batch(batch_id: UUID, body: SettlementCommand):
    return SettlementService().submit(batch_id, body)


@router.post("/{batch_id}/confirm")
def confirm_batch(batch_id: UUID, body: SettlementCommand):
    return SettlementService().confirm(batch_id, body)
