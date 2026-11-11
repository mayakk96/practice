"""Confirmed clearing instructions, separate from untrusted reconciliation evidence."""

from __future__ import annotations

import csv
import hashlib
from datetime import date, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, File, UploadFile
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
    func,
    or_,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column
from starlette.concurrency import run_in_threadpool

from . import db
from .common import json_value, now, page_result, validate_page
from .db import Base
from .errors import DomainError


class ClearingRecord(Base):
    __tablename__ = "clearing_record"
    __table_args__ = (
        Index("ix_clearing_business_date", "business_date", "currency", "id"),
        CheckConstraint("amount_minor > 0 AND amount_minor <= 1000000000000", name="ck_clearing_amount"),
        CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_clearing_currency"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("financial_transaction.id"), unique=True)
    network_reference: Mapped[str] = mapped_column(String(100), unique=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    business_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ClearingImport(Base):
    __tablename__ = "clearing_import"
    __table_args__ = (
        CheckConstraint("status IN ('PROCESSING','COMPLETED')", name="ck_clearing_import_status"),
        CheckConstraint(
            "rows_received >= 0 AND accepted >= 0 AND rejected >= 0 AND duplicates >= 0",
            name="ck_clearing_import_counts",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    file_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="PROCESSING")
    rows_received: Mapped[int] = mapped_column(Integer, default=0)
    accepted: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClearingImportRow(Base):
    __tablename__ = "clearing_import_row"
    __table_args__ = (
        UniqueConstraint("import_id", "row_number", name="uq_clearing_import_row"),
        CheckConstraint("row_number > 0", name="ck_clearing_row_number"),
        CheckConstraint("status IN ('ACCEPTED','REJECTED','DUPLICATE')", name="ck_clearing_row_status"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    import_id: Mapped[UUID] = mapped_column(ForeignKey("clearing_import.id"))
    row_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(200))
    clearing_record_id: Mapped[UUID | None] = mapped_column(ForeignKey("clearing_record.id"))


class ClearingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    transaction_id: UUID = Field(alias="transactionId")
    network_reference: Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{1,100}$", alias="networkReference")]
    amount_minor: Annotated[int, Field(strict=True, ge=1, le=1_000_000_000_000, alias="amountMinor")]
    currency: Annotated[str, Field(pattern=r"^(USD|EUR|GBP)$")]
    business_date: date = Field(alias="businessDate")


def _record_view(row: ClearingRecord) -> dict:
    return {
        "id": str(row.id),
        "transactionId": str(row.transaction_id),
        "networkReference": row.network_reference,
        "amountMinor": row.amount_minor,
        "currency": row.currency,
        "businessDate": row.business_date.isoformat(),
        "createdAt": json_value(row.created_at),
    }


def _import_view(row: ClearingImport, duplicate_file: bool = False) -> dict:
    return {
        "id": str(row.id),
        "fileName": row.file_name,
        "status": row.status,
        "rowsReceived": row.rows_received,
        "accepted": row.accepted,
        "rejected": row.rejected,
        "duplicates": row.duplicates,
        "duplicateFile": duplicate_file,
        "createdAt": json_value(row.created_at),
        "completedAt": json_value(row.completed_at) if row.completed_at else None,
    }


class ClearingService:
    MAX_BYTES = 1_048_576
    MAX_ROWS = 10_000
    HEADER = ["transactionId", "networkReference", "amountMinor", "currency", "businessDate"]

    def __init__(self, factory=None):
        self.factory = factory or db.SessionLocal

    def create(self, body: ClearingRequest | dict) -> dict:
        request = body if isinstance(body, ClearingRequest) else ClearingRequest.model_validate(body)
        try:
            with self.factory.begin() as session:
                record, duplicate = self._record(session, request)
                return {**_record_view(record), "duplicate": duplicate}
        except IntegrityError:
            # A unique-key loser must query after rollback, never in an aborted PG transaction.
            with self.factory.begin() as session:
                existing = self._existing(session, request)
                if existing is not None:
                    return {**_record_view(existing), "duplicate": True}
            raise DomainError(409, "Clearing conflicts with an existing record.") from None

    @staticmethod
    def _existing(session, request):
        existing = session.scalar(
            select(ClearingRecord).where(
                or_(
                    ClearingRecord.transaction_id == request.transaction_id,
                    ClearingRecord.network_reference == request.network_reference,
                )
            )
        )
        if existing is None:
            return None
        if (
            existing.transaction_id,
            existing.network_reference,
            existing.amount_minor,
            existing.currency,
            existing.business_date,
        ) != (
            request.transaction_id,
            request.network_reference,
            request.amount_minor,
            request.currency,
            request.business_date,
        ):
            raise DomainError(409, "Clearing reference was already used with different details.")
        return existing

    def _record(self, session, request):
        from .transactions import get_transaction_locked, transition

        transaction = get_transaction_locked(session, request.transaction_id)
        existing = self._existing(session, request)
        if existing is not None:
            return existing, True
        if transaction.status != "CAPTURED":
            raise DomainError(409, "Only captured transactions can be cleared.")
        if (transaction.amount_minor, transaction.currency, transaction.business_date) != (
            request.amount_minor,
            request.currency,
            request.business_date,
        ):
            raise DomainError(409, "Clearing amount, currency and business date must match the transaction.")
        record = ClearingRecord(
            transaction_id=request.transaction_id,
            network_reference=request.network_reference,
            amount_minor=request.amount_minor,
            currency=request.currency,
            business_date=request.business_date,
        )
        session.add(record)
        session.flush()
        transition(session, transaction, "CLEARED", "Confirmed clearing record accepted")
        session.flush()
        return record, False

    def get(self, record_id: UUID) -> dict:
        with self.factory() as session:
            row = session.get(ClearingRecord, UUID(str(record_id)))
            if row is None:
                raise DomainError(404, "Clearing record was not found.")
            return _record_view(row)

    def list(self, page=0, size=20) -> dict:
        validate_page(page, size)
        with self.factory() as session:
            total = session.scalar(select(func.count()).select_from(ClearingRecord))
            records = session.scalars(
                select(ClearingRecord)
                .order_by(ClearingRecord.created_at, ClearingRecord.id)
                .offset(page * size)
                .limit(size)
            ).all()
            return page_result([_record_view(row) for row in records], page, size, total)

    @classmethod
    def _parse_file(cls, content: bytes) -> list[str]:
        if not content or len(content) > cls.MAX_BYTES:
            raise DomainError(400, "CSV file must contain 1 through 1048576 bytes.")
        try:
            text = content.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError:
            raise DomainError(400, "CSV must use UTF-8 encoding.") from None
        lines = text.splitlines()
        if not lines or lines[0].split(",") != cls.HEADER:
            raise DomainError(400, "CSV header must be " + ",".join(cls.HEADER) + ".")
        rows = lines[1:]
        if not 1 <= len(rows) <= cls.MAX_ROWS:
            raise DomainError(400, "CSV must contain 1 through 10000 data records.")
        return rows

    @classmethod
    def _parse_row(cls, line: str) -> ClearingRequest:
        values = next(csv.reader([line], strict=True))
        if len(values) != len(cls.HEADER):
            raise ValueError("Expected five CSV fields")
        body = dict(zip(cls.HEADER, values, strict=True))
        # Reject decimals/exponents and preserve integer money at the ingestion boundary.
        if not body["amountMinor"].isascii() or not body["amountMinor"].isdigit():
            raise ValueError("Amount must be positive integer minor units")
        body["amountMinor"] = int(body["amountMinor"])
        return ClearingRequest.model_validate(body)

    def import_csv(self, content: bytes, file_name: str) -> dict:
        rows = self._parse_file(content)
        digest = hashlib.sha256(content).hexdigest()
        try:
            with self.factory.begin() as session:
                existing = session.scalar(select(ClearingImport).where(ClearingImport.content_hash == digest))
                if existing is not None:
                    return _import_view(existing, True)
                name = file_name.replace("\\", "/").split("/")[-1][:200] or "clearing.csv"
                imported = ClearingImport(
                    content_hash=digest,
                    file_name=name,
                    rows_received=len(rows),
                    accepted=0,
                    rejected=0,
                    duplicates=0,
                )
                session.add(imported)
                session.flush()
                for number, line in enumerate(rows, start=1):
                    record_id = None
                    try:
                        request = self._parse_row(line)
                        # SAVEPOINT rolls back this row's transition, ledger-independent outbox and insert together.
                        with session.begin_nested():
                            record, duplicate = self._record(session, request)
                            record_id = record.id
                        status = "DUPLICATE" if duplicate else "ACCEPTED"
                        reason = (
                            "Identical clearing record already exists" if duplicate else "Clearing confirmed"
                        )
                    except DomainError as error:
                        status, reason = "REJECTED", error.detail[:200]
                    except (ValueError, csv.Error, StopIteration):
                        status, reason = "REJECTED", "Malformed row or invalid field value"
                    except IntegrityError:
                        status, reason = "REJECTED", "Clearing reference conflicts with an existing record"
                    session.add(
                        ClearingImportRow(
                            import_id=imported.id,
                            row_number=number,
                            status=status,
                            reason=reason,
                            clearing_record_id=record_id,
                        )
                    )
                    if status == "ACCEPTED":
                        imported.accepted += 1
                    elif status == "DUPLICATE":
                        imported.duplicates += 1
                    else:
                        imported.rejected += 1
                imported.status = "COMPLETED"
                imported.completed_at = now()
                session.flush()
                return _import_view(imported)
        except IntegrityError:
            with self.factory() as session:
                existing = session.scalar(select(ClearingImport).where(ClearingImport.content_hash == digest))
                if existing is not None:
                    return _import_view(existing, True)
            raise DomainError(409, "Concurrent clearing import conflict; retry the entire file.") from None

    def get_import(self, import_id: UUID) -> dict:
        with self.factory() as session:
            imported = session.get(ClearingImport, UUID(str(import_id)))
            if imported is None:
                raise DomainError(404, "Clearing import was not found.")
            return _import_view(imported)

    def import_rows(self, import_id: UUID, page=0, size=20) -> dict:
        validate_page(page, size)
        with self.factory() as session:
            if session.get(ClearingImport, UUID(str(import_id))) is None:
                raise DomainError(404, "Clearing import was not found.")
            query = select(ClearingImportRow).where(ClearingImportRow.import_id == UUID(str(import_id)))
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            records = session.scalars(
                query.order_by(ClearingImportRow.row_number).offset(page * size).limit(size)
            ).all()
            return page_result(
                [
                    {
                        "rowNumber": row.row_number,
                        "status": row.status,
                        "reason": row.reason,
                        "clearingRecordId": str(row.clearing_record_id) if row.clearing_record_id else None,
                    }
                    for row in records
                ],
                page,
                size,
                total,
            )


router = APIRouter(prefix="/api/clearing", tags=["clearing"])


@router.post("/records", status_code=201)
def create_record(body: ClearingRequest):
    return ClearingService().create(body)


@router.get("/records")
def list_records(page: int = 0, size: int = 20):
    return ClearingService().list(page, size)


@router.post("/import", status_code=201)
async def import_file(file: UploadFile = File(...)):
    content = await file.read(ClearingService.MAX_BYTES + 1)
    return await run_in_threadpool(ClearingService().import_csv, content, file.filename or "clearing.csv")


@router.get("/imports/{import_id}")
def get_import(import_id: UUID):
    return ClearingService().get_import(import_id)


@router.get("/imports/{import_id}/rows")
def get_import_rows(import_id: UUID, page: int = 0, size: int = 20):
    return ClearingService().import_rows(import_id, page, size)


@router.get("/{record_id}")
def get_record(record_id: UUID):
    return ClearingService().get(record_id)
