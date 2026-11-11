"""Bounded currency-separated reporting from Kafka projections or an explicit demo fallback."""

from __future__ import annotations

import os
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import case, func, select

from . import db
from .common import json_value
from .errors import DomainError
from .events import ExceptionProjection, OutboxEvent, SettlementProjection, TransactionProjection

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.title() for part in rest)


def _value(value: Any) -> Any:
    # PostgreSQL SUM(bigint) is NUMERIC; serialize exact integer aggregates as JSON integers.
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise RuntimeError("Non-integral monetary aggregate")
        return int(value)
    return json_value(value)


class AnalyticsService:
    def __init__(self, factory=None, events_enabled: bool | None = None):
        self.factory = factory or db.SessionLocal
        self.events_enabled = (
            events_enabled
            if events_enabled is not None
            else os.getenv("EVENTS_ENABLED", "false").lower() == "true"
        )

    def _table(self, kind):
        if self.events_enabled:
            return {
                "transaction": TransactionProjection.__table__,
                "settlement": SettlementProjection.__table__,
                "exception": ExceptionProjection.__table__,
            }[kind]
        # Demo remains runnable without Kafka while reporting its actual data source.
        from .models import FinancialTransaction

        if kind == "transaction":
            return FinancialTransaction.__table__
        if kind == "settlement":
            from .settlement import SettlementBatch

            return SettlementBatch.__table__
        from .exceptions import OperationalException

        return OperationalException.__table__

    @staticmethod
    def _bounds(page, size):
        if type(page) is not int or type(size) is not int or page < 0 or not 1 <= size <= 100:
            raise DomainError(400, "page must be non-negative and size must be between 1 and 100")

    @staticmethod
    def _filters(table, day, currency):
        conditions = []
        if day is not None:
            try:
                day = date.fromisoformat(day) if isinstance(day, str) else day
            except ValueError:
                raise DomainError(400, "businessDate must be an ISO date") from None
            conditions.append(table.c.business_date == day)
        if currency is not None:
            if currency not in {"USD", "EUR", "GBP"}:
                raise DomainError(400, "Unsupported currency")
            conditions.append(table.c.currency == currency)
        return conditions

    def _page(self, statement, order, page, size):
        self._bounds(page, size)
        with self.factory() as session:
            count = session.scalar(select(func.count()).select_from(statement.subquery()))
            items = (
                session.execute(statement.order_by(*order).offset(page * size).limit(size)).mappings().all()
            )
            pending = session.scalar(
                select(func.count()).select_from(OutboxEvent).where(OutboxEvent.published_at.is_(None))
            )
        return {
            "source": "KAFKA_PROJECTION" if self.events_enabled else "DEMO_WRITE_MODEL",
            "items": [{_camel(key): _value(value) for key, value in row.items()} for row in items],
            "page": page,
            "size": size,
            "total": count,
            "outboxPending": pending,
        }

    def daily(
        self, day: date | str | None = None, currency: str | None = None, page: int = 0, size: int = 20
    ):
        table = self._table("transaction")
        c = table.c
        statement = (
            select(
                c.business_date,
                c.currency,
                func.count().label("transaction_count"),
                func.sum(c.amount_minor).label("volume_minor"),
                func.sum(case((c.status == "DECLINED", 1), else_=0)).label("declined_count"),
                func.sum(
                    case(
                        (
                            c.status.in_(
                                ("AUTHORIZED", "CAPTURED", "CLEARED", "SETTLED", "REFUNDED", "REVERSED")
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("authorization_success_count"),
                func.sum(case((c.status.in_(("SETTLED", "REFUNDED")), c.amount_minor), else_=0)).label(
                    "settled_minor"
                ),
            )
            .where(*self._filters(table, day, currency))
            .group_by(c.business_date, c.currency)
        )
        result = self._page(statement, (c.business_date, c.currency), page, size)
        for item in result["items"]:
            count = Decimal(item["transactionCount"])
            decisions = Decimal(item["authorizationSuccessCount"] + item["declinedCount"])
            item["authorizationDecisionCount"] = int(decisions)
            item["averageAmountMinor"] = int(
                (Decimal(item["volumeMinor"]) / count).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
            )
            item["authorizationSuccessPercent"] = (
                str(
                    (Decimal(item["authorizationSuccessCount"]) * 100 / decisions).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_EVEN
                    )
                )
                if decisions
                else None
            )
            item["declinePercent"] = (
                str(
                    (Decimal(item["declinedCount"]) * 100 / decisions).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_EVEN
                    )
                )
                if decisions
                else None
            )
        return result

    def transactions(self, day=None, currency=None, page=0, size=20):
        table = self._table("transaction")
        c = table.c
        statement = select(
            c.id,
            c.status,
            c.transaction_type,
            c.amount_minor,
            c.currency,
            c.business_date,
            c.version,
            c.updated_at,
        ).where(*self._filters(table, day, currency))
        result = self._page(statement, (c.business_date, c.id), page, size)
        for item in result["items"]:
            item["id"] = str(item["id"])
        return result

    def settlements(self, day=None, currency=None, page=0, size=20):
        table = self._table("settlement")
        c = table.c
        statement = select(
            c.id,
            c.status,
            c.business_date,
            c.currency,
            c.transaction_count,
            c.gross_debit_minor,
            c.gross_credit_minor,
            c.net_minor,
            c.version,
        ).where(*self._filters(table, day, currency))
        result = self._page(statement, (c.business_date, c.id), page, size)
        for item in result["items"]:
            item["id"] = str(item["id"])
        return result

    def exceptions(self, page=0, size=20):
        table = self._table("exception")
        c = table.c
        statement = select(c.status, c.category, c.severity, func.count().label("exception_count")).group_by(
            c.status, c.category, c.severity
        )
        return self._page(statement, (c.status, c.category, c.severity), page, size)


@router.get("/daily")
def daily(
    businessDate: date | None = None,
    currency: str | None = None,
    page: int = Query(0, ge=0),
    size: int = Query(20, ge=1, le=100),
):
    return AnalyticsService().daily(businessDate, currency, page, size)


@router.get("/transactions")
def transactions(
    businessDate: date | None = None,
    currency: str | None = None,
    page: int = Query(0, ge=0),
    size: int = Query(20, ge=1, le=100),
):
    return AnalyticsService().transactions(businessDate, currency, page, size)


@router.get("/settlement")
def settlements(
    businessDate: date | None = None,
    currency: str | None = None,
    page: int = Query(0, ge=0),
    size: int = Query(20, ge=1, le=100),
):
    return AnalyticsService().settlements(businessDate, currency, page, size)


@router.get("/exceptions")
def exceptions(page: int = Query(0, ge=0), size: int = Query(20, ge=1, le=100)):
    return AnalyticsService().exceptions(page, size)
