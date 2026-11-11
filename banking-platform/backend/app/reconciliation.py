"""Immutable, currency-scoped settlement reconciliation and external evidence ingestion."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Response
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
    Text,
    UniqueConstraint,
    Uuid,
    and_,
    func,
    or_,
    select,
)
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.errors import DomainError

MAX_RUN_RECORDS = 10_000
CURRENCIES = {"USD", "EUR", "GBP"}
ELIGIBLE_STATUSES = ("CLEARED", "SETTLED", "REFUNDED")


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return (
        value.replace(tzinfo=UTC).isoformat()
        if value and value.tzinfo is None
        else value.isoformat()
        if value
        else None
    )


def _page(page: int, size: int) -> None:
    if page < 0 or not 1 <= size <= 100:
        raise DomainError(400, "page must be non-negative and size must be between 1 and 100.")


def _factory(factory):
    if factory is not None:
        return factory
    from app import db

    return db.SessionLocal


class ExternalImport(Base):
    __tablename__ = "external_reconciliation_import"
    __table_args__ = (CheckConstraint("record_count BETWEEN 1 AND 1000", name="ck_external_import_count"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    source_reference: Mapped[str] = mapped_column(String(100))
    record_count: Mapped[int] = mapped_column(Integer)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ExternalReconciliationRecord(Base):
    __tablename__ = "external_reconciliation_record"
    __table_args__ = (
        CheckConstraint(
            "amount_minor <> 0 AND amount_minor BETWEEN -1000000000000 AND 1000000000000",
            name="ck_external_recon_amount",
        ),
        CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_external_recon_currency"),
        CheckConstraint("status IN ('SETTLED','CLEARED','FAILED')", name="ck_external_recon_status"),
        CheckConstraint("received_date >= business_date", name="ck_external_recon_received_date"),
        Index("ix_external_recon_date_currency_ref", "business_date", "currency", "external_reference"),
        Index("ix_external_recon_reference", "external_reference", "business_date"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    import_id: Mapped[UUID] = mapped_column(ForeignKey("external_reconciliation_import.id"))
    external_reference: Mapped[str] = mapped_column(String(100))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20))
    business_date: Mapped[date] = mapped_column(Date)
    received_date: Mapped[date] = mapped_column(Date)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_run"
    __table_args__ = (
        CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_recon_run_currency"),
        CheckConstraint("status IN ('COMPLETED')", name="ck_recon_run_status"),
        CheckConstraint(
            "records_processed = records_matched + records_unmatched", name="ck_recon_run_counts"
        ),
        CheckConstraint(
            "records_processed >= 0 AND records_matched >= 0 AND records_unmatched >= 0",
            name="ck_recon_nonnegative_counts",
        ),
        CheckConstraint(
            "variance_minor = total_internal_minor - total_external_minor", name="ck_recon_run_variance"
        ),
        Index("ix_recon_run_business_date_currency", "business_date", "currency", "started_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    previous_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("reconciliation_run.id"), nullable=True)
    business_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default="COMPLETED")
    records_processed: Mapped[int] = mapped_column(Integer)
    records_matched: Mapped[int] = mapped_column(Integer)
    records_unmatched: Mapped[int] = mapped_column(Integer)
    total_internal_minor: Mapped[int] = mapped_column(BigInteger)
    total_external_minor: Mapped[int] = mapped_column(BigInteger)
    variance_minor: Mapped[int] = mapped_column(BigInteger)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReconciliationResult(Base):
    __tablename__ = "reconciliation_result"
    __table_args__ = (
        CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_recon_result_currency"),
        UniqueConstraint("run_id", "external_reference", name="uq_recon_run_reference"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("reconciliation_run.id"))
    external_reference: Mapped[str] = mapped_column(String(100))
    transaction_id: Mapped[UUID | None] = mapped_column(ForeignKey("financial_transaction.id"), nullable=True)
    classifications: Mapped[str] = mapped_column(String(400))
    internal_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    external_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    variance_minor: Mapped[int] = mapped_column(BigInteger)
    internal_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    external_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    internal_business_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    external_business_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    internal_version: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    external_record_ids: Mapped[str] = mapped_column(Text)


class ExternalRecordBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    external_reference: str = Field(
        alias="externalReference", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$"
    )
    amount_minor: int = Field(alias="amountMinor", strict=True, ge=-1_000_000_000_000, le=1_000_000_000_000)
    currency: Literal["USD", "EUR", "GBP"]
    status: Literal["SETTLED", "CLEARED", "FAILED"]
    business_date: date = Field(alias="businessDate")
    received_date: date | None = Field(default=None, alias="receivedDate")


class ExternalImportBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    source_reference: str = Field(
        default="DEMO-MANUAL",
        alias="sourceReference",
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    records: list[ExternalRecordBody] = Field(min_length=1, max_length=1000)


class RunBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    business_date: date = Field(alias="businessDate")
    currency: Literal["USD", "EUR", "GBP"]


@dataclass(frozen=True)
class InternalEvidence:
    id: UUID
    external_reference: str
    amount_minor: int
    currency: str
    status: str
    business_date: date
    version: int = 0


@dataclass(frozen=True)
class ExternalEvidence:
    id: UUID
    external_reference: str
    amount_minor: int
    currency: str
    status: str
    business_date: date
    received_date: date


@dataclass(frozen=True)
class Comparison:
    external_reference: str
    transaction_id: UUID | None
    classifications: tuple[str, ...]
    internal_amount_minor: int | None
    external_amount_minor: int | None
    variance_minor: int
    internal_status: str | None
    external_status: str | None
    internal_business_date: date | None
    external_business_date: date | None
    internal_version: int | None
    external_record_ids: tuple[UUID, ...]


def compare_records(
    internal: list[InternalEvidence], external: list[ExternalEvidence], business_date: date, currency: str
) -> list[Comparison]:
    """One deterministic result per reference; totals never mix currencies or dates.

    Duplicate external amounts all contribute to the scoped external total. Foreign
    currency evidence contributes zero to that total and is explicitly flagged.
    """
    if currency not in CURRENCIES:
        raise DomainError(400, "Unsupported reconciliation currency.")
    by_internal = {row.external_reference: row for row in internal}
    if len(by_internal) != len(internal):
        raise DomainError(409, "Duplicate internal references violate the transaction identity control.")
    by_external: dict[str, list[ExternalEvidence]] = defaultdict(list)
    for row in external:
        if row.external_reference in by_internal or (
            row.business_date == business_date and row.currency == currency
        ):
            by_external[row.external_reference].append(row)
    results = []
    for reference in sorted(set(by_internal) | set(by_external)):
        own = by_internal.get(reference)
        others = sorted(
            by_external.get(reference, []), key=lambda row: (row.business_date, row.currency, str(row.id))
        )
        scoped = [row for row in others if row.business_date == business_date and row.currency == currency]
        internal_amount = (
            own.amount_minor
            if own and own.business_date == business_date and own.currency == currency
            else None
        )
        external_amount = sum(row.amount_minor for row in scoped) if scoped else None
        flags = []
        if not own:
            flags.append("MISSING_INTERNAL")
        if not others:
            flags.append("MISSING_EXTERNAL")
        if len(others) > 1:
            flags.append("DUPLICATE_EXTERNAL")
        if own and others:
            if any(row.currency != own.currency for row in others):
                flags.append("CURRENCY_MISMATCH")
            if own.business_date != business_date or any(
                row.business_date != business_date or row.received_date > business_date for row in others
            ):
                flags.append("LATE_ARRIVAL")
            if scoped and internal_amount is not None and external_amount != internal_amount:
                flags.append("AMOUNT_MISMATCH")
            if own.status not in {"SETTLED", "REFUNDED"} or any(row.status != "SETTLED" for row in others):
                flags.append("STATUS_MISMATCH")
        results.append(
            Comparison(
                reference,
                own.id if own else None,
                tuple(flags) if flags else ("MATCHED",),
                internal_amount,
                external_amount,
                (internal_amount or 0) - (external_amount or 0),
                own.status if own else None,
                ",".join(sorted({row.status for row in others})) or None,
                own.business_date if own else None,
                others[0].business_date if others else None,
                own.version if own else None,
                tuple(row.id for row in others),
            )
        )
    return results


def run_view(row: ReconciliationRun) -> dict:
    return {
        "id": str(row.id),
        "previousRunId": str(row.previous_run_id) if row.previous_run_id else None,
        "businessDate": row.business_date.isoformat(),
        "currency": row.currency,
        "status": row.status,
        "recordsProcessed": row.records_processed,
        "recordsMatched": row.records_matched,
        "recordsUnmatched": row.records_unmatched,
        "totalInternalMinor": row.total_internal_minor,
        "totalExternalMinor": row.total_external_minor,
        "varianceMinor": row.variance_minor,
        "startedAt": _iso(row.started_at),
        "completedAt": _iso(row.completed_at),
    }


def result_view(row: ReconciliationResult) -> dict:
    return {
        "id": str(row.id),
        "runId": str(row.run_id),
        "externalReference": row.external_reference,
        "transactionId": str(row.transaction_id) if row.transaction_id else None,
        "classifications": row.classifications.split(","),
        "internalAmountMinor": row.internal_amount_minor,
        "externalAmountMinor": row.external_amount_minor,
        "currency": row.currency,
        "varianceMinor": row.variance_minor,
        "internalStatus": row.internal_status,
        "externalStatus": row.external_status,
        "internalBusinessDate": row.internal_business_date.isoformat()
        if row.internal_business_date
        else None,
        "externalBusinessDate": row.external_business_date.isoformat()
        if row.external_business_date
        else None,
        "internalVersion": row.internal_version,
        "externalRecordIds": row.external_record_ids.split(",")[:100] if row.external_record_ids else [],
        "externalRecordCount": len(row.external_record_ids.split(",")) if row.external_record_ids else 0,
        "externalRecordsTruncated": bool(
            row.external_record_ids and len(row.external_record_ids.split(",")) > 100
        ),
    }


class ReconciliationService:
    def __init__(self, factory=None):
        self.factory = _factory(factory)

    def import_records(self, body: dict | ExternalImportBody) -> dict:
        data = body if isinstance(body, ExternalImportBody) else ExternalImportBody.model_validate(body)
        normalized = data.model_dump(mode="json", by_alias=True)
        for row in normalized["records"]:
            if row["amountMinor"] == 0:
                raise DomainError(422, "External amountMinor must be nonzero.")
            if row["receivedDate"] is None:
                row["receivedDate"] = row["businessDate"]
            if row["receivedDate"] < row["businessDate"]:
                raise DomainError(422, "receivedDate cannot precede businessDate.")
        fingerprint = sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        try:
            with self.factory.begin() as session:
                existing = session.scalar(
                    select(ExternalImport).where(ExternalImport.fingerprint == fingerprint)
                )
                if existing:
                    return {
                        "importId": str(existing.id),
                        "accepted": existing.record_count,
                        "duplicateImport": True,
                    }
                imported = ExternalImport(
                    fingerprint=fingerprint,
                    source_reference=data.source_reference,
                    record_count=len(data.records),
                )
                session.add(imported)
                session.flush()
                for row in normalized["records"]:
                    session.add(
                        ExternalReconciliationRecord(
                            import_id=imported.id,
                            external_reference=row["externalReference"],
                            amount_minor=row["amountMinor"],
                            currency=row["currency"],
                            status=row["status"],
                            business_date=date.fromisoformat(row["businessDate"]),
                            received_date=date.fromisoformat(row["receivedDate"]),
                        )
                    )
                session.flush()
                return {
                    "importId": str(imported.id),
                    "accepted": imported.record_count,
                    "duplicateImport": False,
                }
        except IntegrityError:
            with self.factory() as session:
                existing = session.scalar(
                    select(ExternalImport).where(ExternalImport.fingerprint == fingerprint)
                )
                if existing:
                    return {
                        "importId": str(existing.id),
                        "accepted": existing.record_count,
                        "duplicateImport": True,
                    }
            raise DomainError(409, "External evidence import conflicted with concurrent data.") from None

    def create_run(self, body: dict | RunBody, previous_run_id: UUID | None = None) -> dict:
        data = body if isinstance(body, RunBody) else RunBody.model_validate(body)
        # Only database work is repeated: no remote calls or partial commits occur.
        for attempt in range(3):
            try:
                return self._create_run(data, previous_run_id)
            except (IntegrityError, OperationalError) as error:
                code = getattr(error.orig, "sqlstate", None)
                if isinstance(error, OperationalError) and code != "40001":
                    # Availability failures are not concurrency conflicts. Let the HTTP
                    # boundary translate an unavailable database to HTTP 503.
                    raise
                retryable = isinstance(error, IntegrityError) or code == "40001"
                if not retryable or attempt == 2:
                    raise DomainError(
                        409, "Concurrent reconciliation changed this snapshot; retry the run."
                    ) from None
        raise AssertionError("unreachable")

    def _create_run(self, data: RunBody, previous_run_id: UUID | None) -> dict:
        from app.events import record_event
        from app.exceptions import create_exception_in_session
        from app.models import FinancialTransaction

        with self.factory.begin() as session:
            # PostgreSQL keeps both evidence reads in the same MVCC snapshot.
            if session.get_bind().dialect.name == "postgresql":
                session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            started_at = _now()
            internal_rows = list(
                session.scalars(
                    select(FinancialTransaction)
                    .where(
                        FinancialTransaction.business_date == data.business_date,
                        FinancialTransaction.currency == data.currency,
                        FinancialTransaction.status.in_(ELIGIBLE_STATUSES),
                    )
                    .order_by(FinancialTransaction.external_reference)
                    .limit(MAX_RUN_RECORDS + 1)
                )
            )
            references = select(FinancialTransaction.external_reference).where(
                FinancialTransaction.business_date == data.business_date,
                FinancialTransaction.currency == data.currency,
                FinancialTransaction.status.in_(ELIGIBLE_STATUSES),
            )
            external_rows = list(
                session.scalars(
                    select(ExternalReconciliationRecord)
                    .where(
                        or_(
                            and_(
                                ExternalReconciliationRecord.business_date == data.business_date,
                                ExternalReconciliationRecord.currency == data.currency,
                            ),
                            ExternalReconciliationRecord.external_reference.in_(references),
                        )
                    )
                    .order_by(
                        ExternalReconciliationRecord.external_reference, ExternalReconciliationRecord.id
                    )
                    .limit(MAX_RUN_RECORDS + 1)
                )
            )
            if len(internal_rows) > MAX_RUN_RECORDS or len(external_rows) > MAX_RUN_RECORDS:
                raise DomainError(
                    422,
                    "A reconciliation snapshot is limited to 10000 internal and external records; partition the business input.",
                )
            # Missing-external checks consider settlement-eligible records only.
            # External evidence can nevertheless reference a known transaction in
            # an earlier or terminal state; retain its identity and classify the
            # state discrepancy instead of claiming that the transaction is absent.
            external_references = {row.external_reference for row in external_rows}
            if external_references:
                known_rows = session.scalars(
                    select(FinancialTransaction)
                    .where(FinancialTransaction.external_reference.in_(external_references))
                    .order_by(FinancialTransaction.external_reference)
                    .limit(MAX_RUN_RECORDS + 1)
                )
                by_id = {row.id: row for row in internal_rows}
                by_id.update((row.id, row) for row in known_rows)
                internal_rows = sorted(by_id.values(), key=lambda row: row.external_reference)
                if len(internal_rows) > MAX_RUN_RECORDS:
                    raise DomainError(
                        422,
                        "A reconciliation snapshot is limited to 10000 internal and external records; partition the business input.",
                    )
            internal = [
                InternalEvidence(
                    row.id,
                    row.external_reference,
                    -row.amount_minor if row.transaction_type == "REFUND" else row.amount_minor,
                    row.currency,
                    row.status,
                    row.business_date,
                    row.version,
                )
                for row in internal_rows
            ]
            external = [
                ExternalEvidence(
                    row.id,
                    row.external_reference,
                    row.amount_minor,
                    row.currency,
                    row.status,
                    row.business_date,
                    row.received_date,
                )
                for row in external_rows
            ]
            compared = compare_records(internal, external, data.business_date, data.currency)
            matched = sum(row.classifications == ("MATCHED",) for row in compared)
            internal_total = sum(row.internal_amount_minor or 0 for row in compared)
            external_total = sum(row.external_amount_minor or 0 for row in compared)
            run = ReconciliationRun(
                previous_run_id=previous_run_id,
                business_date=data.business_date,
                currency=data.currency,
                records_processed=len(compared),
                records_matched=matched,
                records_unmatched=len(compared) - matched,
                total_internal_minor=internal_total,
                total_external_minor=external_total,
                variance_minor=internal_total - external_total,
                status="COMPLETED",
                started_at=started_at,
                completed_at=_now(),
            )
            session.add(run)
            session.flush()
            for item in compared:
                result = ReconciliationResult(
                    run_id=run.id,
                    external_reference=item.external_reference,
                    transaction_id=item.transaction_id,
                    classifications=",".join(item.classifications),
                    internal_amount_minor=item.internal_amount_minor,
                    external_amount_minor=item.external_amount_minor,
                    currency=data.currency,
                    variance_minor=item.variance_minor,
                    internal_status=item.internal_status,
                    external_status=item.external_status,
                    internal_business_date=item.internal_business_date,
                    external_business_date=item.external_business_date,
                    internal_version=item.internal_version,
                    external_record_ids=",".join(str(item_id) for item_id in item.external_record_ids),
                )
                session.add(result)
                session.flush()
                if item.classifications != ("MATCHED",):
                    create_exception_in_session(session, run, result)
                    payload = {
                        "businessDate": data.business_date.isoformat(),
                        "currency": data.currency,
                        "category": "RECONCILIATION",
                        "reconciliationRunId": str(run.id),
                    }
                    if item.transaction_id:
                        payload["transactionId"] = str(item.transaction_id)
                    record_event(session, "ReconciliationMismatchDetected", result.id, payload)
            record_event(
                session,
                "ReconciliationCompleted",
                run.id,
                {
                    "businessDate": data.business_date.isoformat(),
                    "currency": data.currency,
                    "matched": matched,
                    "unmatched": run.records_unmatched,
                    "varianceMinor": run.variance_minor,
                    "status": "COMPLETED",
                },
            )
            self._reconcile_matched_batches(session, data, compared)
            run.completed_at = _now()
            return run_view(run)

    @staticmethod
    def _reconcile_matched_batches(session, data, compared) -> None:
        from app.settlement import SettlementBatch, SettlementItem, reconcile_in_session

        matched_ids = {row.transaction_id for row in compared if row.classifications == ("MATCHED",)}
        batches = list(
            session.scalars(
                select(SettlementBatch)
                .where(
                    SettlementBatch.business_date == data.business_date,
                    SettlementBatch.currency == data.currency,
                    SettlementBatch.status == "CONFIRMED",
                )
                .with_for_update()
            )
        )
        for batch in batches:
            item_ids = set(
                session.scalars(
                    select(SettlementItem.transaction_id).where(SettlementItem.batch_id == batch.id)
                )
            )
            if item_ids and item_ids <= matched_ids:
                reconcile_in_session(
                    session,
                    batch,
                    batch.version,
                    "All settlement items matched immutable reconciliation evidence.",
                )

    def get_run(self, run_id: UUID | str) -> dict:
        with self.factory() as session:
            row = session.get(ReconciliationRun, UUID(str(run_id)))
            if row is None:
                raise DomainError(404, "Reconciliation run was not found.")
            return run_view(row)

    def list_runs(self, page: int = 0, size: int = 20) -> dict:
        _page(page, size)
        with self.factory() as session:
            total = session.scalar(select(func.count()).select_from(ReconciliationRun))
            rows = session.scalars(
                select(ReconciliationRun)
                .order_by(ReconciliationRun.started_at.desc(), ReconciliationRun.id)
                .offset(page * size)
                .limit(size)
            )
            return {"items": [run_view(row) for row in rows], "page": page, "size": size, "total": total}

    def mismatches(self, run_id: UUID | str, page: int = 0, size: int = 20) -> dict:
        _page(page, size)
        self.get_run(run_id)
        with self.factory() as session:
            where = (
                ReconciliationResult.run_id == UUID(str(run_id)),
                ReconciliationResult.classifications != "MATCHED",
            )
            total = session.scalar(select(func.count()).select_from(ReconciliationResult).where(*where))
            rows = session.scalars(
                select(ReconciliationResult)
                .where(*where)
                .order_by(ReconciliationResult.external_reference, ReconciliationResult.id)
                .offset(page * size)
                .limit(size)
            )
            return {"items": [result_view(row) for row in rows], "page": page, "size": size, "total": total}

    def get_result(self, result_id: UUID | str) -> dict:
        with self.factory() as session:
            row = session.get(ReconciliationResult, UUID(str(result_id)))
            if row is None:
                raise DomainError(404, "Reconciliation result was not found.")
            return result_view(row)

    def rerun(self, run_id: UUID | str) -> dict:
        previous = self.get_run(run_id)
        return self.create_run(
            {"businessDate": previous["businessDate"], "currency": previous["currency"]}, UUID(previous["id"])
        )


router = APIRouter(prefix="/api/reconciliation", tags=["Reconciliation"])


@router.post("/external-records", status_code=201)
def import_external_records(body: ExternalImportBody, response: Response):
    result = ReconciliationService().import_records(body)
    if result["duplicateImport"]:
        response.status_code = 200
    return result


@router.post("/runs", status_code=201)
def create_reconciliation_run(body: RunBody):
    return ReconciliationService().create_run(body)


@router.get("/runs")
def list_reconciliation_runs(
    page: Annotated[int, Query(ge=0)] = 0, size: Annotated[int, Query(ge=1, le=100)] = 20
):
    return ReconciliationService().list_runs(page, size)


@router.get("/runs/{run_id}")
def get_reconciliation_run(run_id: UUID):
    return ReconciliationService().get_run(run_id)


@router.get("/runs/{run_id}/mismatches")
def list_reconciliation_mismatches(
    run_id: UUID, page: Annotated[int, Query(ge=0)] = 0, size: Annotated[int, Query(ge=1, le=100)] = 20
):
    return ReconciliationService().mismatches(run_id, page, size)


@router.get("/results/{result_id}")
def get_reconciliation_result(result_id: UUID):
    return ReconciliationService().get_result(result_id)


@router.post("/runs/{run_id}/rerun", status_code=201)
def rerun_reconciliation(run_id: UUID):
    return ReconciliationService().rerun(run_id)
