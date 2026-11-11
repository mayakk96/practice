"""Audited operational dispositions; resolving an issue never changes money."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    select,
    update,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.errors import DomainError


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return (value.replace(tzinfo=UTC) if value.tzinfo is None else value).isoformat()


def _factory(factory):
    if factory is not None:
        return factory
    from app import db

    return db.SessionLocal


def _identity() -> tuple[str, str]:
    from app.common import actor, correlation_id

    return actor(), correlation_id()


def _page(page: int, size: int) -> None:
    if page < 0 or not 1 <= size <= 100:
        raise DomainError(400, "page must be non-negative and size must be between 1 and 100.")


class OperationalException(Base):
    __tablename__ = "operational_exception"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN','INVESTIGATING','RESOLVED')", name="ck_operational_exception_status"
        ),
        CheckConstraint("severity IN ('MEDIUM','HIGH')", name="ck_operational_exception_severity"),
        CheckConstraint("version >= 0", name="ck_operational_exception_version"),
        Index("ix_exception_status_created", "status", "created_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    issue_key: Mapped[str] = mapped_column(String(64), unique=True)
    transaction_id: Mapped[UUID | None] = mapped_column(ForeignKey("financial_transaction.id"), nullable=True)
    reconciliation_run_id: Mapped[UUID] = mapped_column(ForeignKey("reconciliation_run.id"))
    reconciliation_result_id: Mapped[UUID] = mapped_column(ForeignKey("reconciliation_result.id"))
    category: Mapped[str] = mapped_column(String(30), default="RECONCILIATION")
    severity: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    reason: Mapped[str] = mapped_column(String(500))
    assigned_team: Mapped[str] = mapped_column(String(50), default="PAYMENTS_OPS")
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class OperationalExceptionHistory(Base):
    __tablename__ = "operational_exception_history"
    __table_args__ = (UniqueConstraint("exception_id", "version", name="uq_exception_history_version"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    exception_id: Mapped[UUID] = mapped_column(ForeignKey("operational_exception.id"))
    previous_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_status: Mapped[str] = mapped_column(String(20))
    assigned_team: Mapped[str] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(100))
    correlation_id: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(BigInteger)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ExceptionUpdateBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    status: Literal["INVESTIGATING", "RESOLVED"]
    assigned_team: str = Field(
        alias="assignedTeam", min_length=1, max_length=50, pattern=r"^[A-Z][A-Z0-9_ -]*$"
    )
    resolution_notes: str | None = Field(default=None, alias="resolutionNotes", max_length=2000)
    version: int = Field(ge=0, strict=True)


def exception_view(row: OperationalException) -> dict:
    return {
        "id": str(row.id),
        "transactionId": str(row.transaction_id) if row.transaction_id else None,
        "reconciliationRunId": str(row.reconciliation_run_id),
        "reconciliationResultId": str(row.reconciliation_result_id),
        "category": row.category,
        "severity": row.severity,
        "status": row.status,
        "reason": row.reason,
        "assignedTeam": row.assigned_team,
        "resolutionNotes": row.resolution_notes,
        "version": row.version,
        "createdAt": _iso(row.created_at),
        "updatedAt": _iso(row.updated_at),
    }


def create_exception_in_session(session, run, result) -> None:
    """Stable evidence identity avoids duplicate cases on reruns without hiding new facts.

    A resolved disposition is retained when identical evidence is rerun. A changed
    amount/classification/status creates a new issue; the run always retains its
    own mismatch independently of operational disposition.
    """
    from app.events import record_event

    evidence = {
        "reference": result.external_reference,
        "businessDate": run.business_date.isoformat(),
        "currency": run.currency,
        "classifications": result.classifications,
        "internalAmount": result.internal_amount_minor,
        "externalAmount": result.external_amount_minor,
        "internalStatus": result.internal_status,
        "externalStatus": result.external_status,
        "externalBusinessDate": str(result.external_business_date),
    }
    issue_key = sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if session.scalar(select(OperationalException).where(OperationalException.issue_key == issue_key)):
        return
    now = _now()
    issue = OperationalException(
        issue_key=issue_key,
        transaction_id=result.transaction_id,
        reconciliation_run_id=run.id,
        reconciliation_result_id=result.id,
        category="RECONCILIATION",
        severity="HIGH" if result.variance_minor else "MEDIUM",
        status="OPEN",
        reason=f"Reconciliation detected {result.classifications}.",
        assigned_team="PAYMENTS_OPS",
        version=0,
        created_at=now,
        updated_at=now,
    )
    session.add(issue)
    session.flush()
    actor, correlation = _identity()
    session.add(
        OperationalExceptionHistory(
            exception_id=issue.id,
            previous_status=None,
            new_status="OPEN",
            assigned_team=issue.assigned_team,
            notes="Created from immutable reconciliation evidence.",
            actor=actor,
            correlation_id=correlation,
            version=0,
            changed_at=now,
        )
    )
    payload = {
        "status": "OPEN",
        "category": issue.category,
        "severity": issue.severity,
        "version": 0,
        "currency": run.currency,
        "businessDate": run.business_date.isoformat(),
        "reconciliationRunId": str(run.id),
    }
    if issue.transaction_id:
        payload["transactionId"] = str(issue.transaction_id)
    record_event(session, "OperationalExceptionCreated", issue.id, payload)


class OperationalExceptionService:
    def __init__(self, factory=None):
        self.factory = _factory(factory)

    def get(self, exception_id: UUID | str) -> dict:
        with self.factory() as session:
            row = session.get(OperationalException, UUID(str(exception_id)))
            if row is None:
                raise DomainError(404, "Operational exception was not found.")
            return exception_view(row)

    def list(self, page: int = 0, size: int = 20, status: str | None = None) -> dict:
        _page(page, size)
        if status is not None and status not in {"OPEN", "INVESTIGATING", "RESOLVED"}:
            raise DomainError(400, "Unsupported exception status.")
        with self.factory() as session:
            where = (OperationalException.status == status,) if status else ()
            total = session.scalar(select(func.count()).select_from(OperationalException).where(*where))
            rows = session.scalars(
                select(OperationalException)
                .where(*where)
                .order_by(OperationalException.created_at, OperationalException.id)
                .offset(page * size)
                .limit(size)
            )
            return {
                "items": [exception_view(row) for row in rows],
                "page": page,
                "size": size,
                "total": total,
            }

    def history(self, exception_id: UUID | str, page: int = 0, size: int = 20) -> dict:
        _page(page, size)
        self.get(exception_id)
        with self.factory() as session:
            where = OperationalExceptionHistory.exception_id == UUID(str(exception_id))
            total = session.scalar(select(func.count()).select_from(OperationalExceptionHistory).where(where))
            rows = session.scalars(
                select(OperationalExceptionHistory)
                .where(where)
                .order_by(OperationalExceptionHistory.version, OperationalExceptionHistory.id)
                .offset(page * size)
                .limit(size)
            )
            items = [
                {
                    "id": str(row.id),
                    "exceptionId": str(row.exception_id),
                    "previousStatus": row.previous_status,
                    "newStatus": row.new_status,
                    "assignedTeam": row.assigned_team,
                    "notes": row.notes,
                    "actor": row.actor,
                    "correlationId": row.correlation_id,
                    "version": row.version,
                    "changedAt": _iso(row.changed_at),
                }
                for row in rows
            ]
            return {"items": items, "page": page, "size": size, "total": total}

    def update(self, exception_id: UUID | str, body: dict | ExceptionUpdateBody) -> dict:
        from app.events import record_event
        from app.reconciliation import ReconciliationRun

        data = body if isinstance(body, ExceptionUpdateBody) else ExceptionUpdateBody.model_validate(body)
        notes = data.resolution_notes.strip() if data.resolution_notes else None
        if data.status == "RESOLVED" and not notes:
            raise DomainError(422, "Resolving an exception requires investigation and resolution notes.")
        with self.factory.begin() as session:
            row = session.get(OperationalException, UUID(str(exception_id)))
            if row is None:
                raise DomainError(404, "Operational exception was not found.")
            if row.version != data.version:
                raise DomainError(
                    409, "Exception was changed by another operator; reload its current version."
                )
            permitted = {
                "OPEN": {"INVESTIGATING"},
                "INVESTIGATING": {"INVESTIGATING", "RESOLVED"},
                "RESOLVED": set(),
            }
            if data.status not in permitted[row.status]:
                raise DomainError(
                    409, "Exception transition is not permitted; investigate before resolution."
                )
            previous = row.status
            now = _now()
            changed = session.execute(
                update(OperationalException)
                .where(OperationalException.id == row.id, OperationalException.version == data.version)
                .values(
                    status=data.status,
                    assigned_team=data.assigned_team.strip(),
                    resolution_notes=notes,
                    version=data.version + 1,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount != 1:
                raise DomainError(
                    409, "Exception was changed by another operator; reload its current version."
                )
            actor, correlation = _identity()
            session.add(
                OperationalExceptionHistory(
                    exception_id=row.id,
                    previous_status=previous,
                    new_status=data.status,
                    assigned_team=data.assigned_team.strip(),
                    notes=notes,
                    actor=actor,
                    correlation_id=correlation,
                    version=data.version + 1,
                    changed_at=now,
                )
            )
            run = session.get(ReconciliationRun, row.reconciliation_run_id)
            payload = {
                "status": data.status,
                "category": row.category,
                "severity": row.severity,
                "version": data.version + 1,
                "currency": run.currency,
                "businessDate": run.business_date.isoformat(),
                "reconciliationRunId": str(run.id),
            }
            if row.transaction_id:
                payload["transactionId"] = str(row.transaction_id)
            record_event(session, "OperationalExceptionUpdated", row.id, payload)
            session.refresh(row)
            return exception_view(row)


router = APIRouter(prefix="/api/exceptions", tags=["Operational exceptions"])


@router.get("")
def list_exceptions(
    page: Annotated[int, Query(ge=0)] = 0,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: str | None = None,
):
    return OperationalExceptionService().list(page, size, status)


@router.get("/{exception_id}")
def get_exception(exception_id: UUID):
    return OperationalExceptionService().get(exception_id)


@router.get("/{exception_id}/history")
def exception_history(
    exception_id: UUID, page: Annotated[int, Query(ge=0)] = 0, size: Annotated[int, Query(ge=1, le=100)] = 20
):
    return OperationalExceptionService().history(exception_id, page, size)


@router.patch("/{exception_id}")
def update_exception(exception_id: UUID, body: ExceptionUpdateBody):
    return OperationalExceptionService().update(exception_id, body)
