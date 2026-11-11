from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from .common import now
from .db import Base


class Customer(Base):
    __tablename__ = "customer"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    external_reference: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class BankAccount(Base):
    __tablename__ = "bank_account"
    __table_args__ = (
        CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_account_currency"),
        CheckConstraint("status IN ('ACTIVE','BLOCKED','CLOSED')", name="ck_account_status"),
        Index("ix_account_customer", "customer_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customer.id"))
    account_reference: Mapped[str] = mapped_column(String(100), unique=True)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class FinancialTransaction(Base):
    __tablename__ = "financial_transaction"
    __table_args__ = (
        UniqueConstraint("id", "amount_minor", "currency", name="uq_tx_money"),
        CheckConstraint("amount_minor > 0 AND amount_minor <= 1000000000000", name="ck_tx_amount"),
        CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_tx_currency"),
        CheckConstraint(
            "transaction_type IN ('CARD_PURCHASE','ACCOUNT_TRANSFER','REFUND')", name="ck_tx_type"
        ),
        CheckConstraint(
            "status IN ('RECEIVED','VALIDATED','AUTHORIZED','DECLINED','CAPTURED','CLEARED','SETTLED','REVERSED','REFUNDED')",
            name="ck_tx_status",
        ),
        Index("ix_tx_status_date", "status", "business_date", "id"),
        Index("ix_tx_account_time", "source_account_id", "created_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    external_reference: Mapped[str] = mapped_column(String(100), unique=True)
    transaction_type: Mapped[str] = mapped_column(String(30))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    source_account_id: Mapped[UUID] = mapped_column(ForeignKey("bank_account.id"))
    counterparty_reference: Mapped[str] = mapped_column(String(100))
    original_transaction_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("financial_transaction.id"), unique=True
    )
    status: Mapped[str] = mapped_column(String(30), default="RECEIVED")
    network_reference: Mapped[str | None] = mapped_column(String(100))
    business_date: Mapped[date] = mapped_column(Date)
    version: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class IdempotencyClaim(Base):
    __tablename__ = "transaction_idempotency"
    request_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    transaction_id: Mapped[UUID | None] = mapped_column(ForeignKey("financial_transaction.id"))
    response_json: Mapped[str | None] = mapped_column(String(8000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TransactionHistory(Base):
    __tablename__ = "transaction_history"
    __table_args__ = (UniqueConstraint("transaction_id", "version", name="uq_history_version"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("financial_transaction.id"))
    previous_status: Mapped[str | None] = mapped_column(String(30))
    new_status: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(String(500))
    actor: Mapped[str] = mapped_column(String(100))
    correlation_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(BigInteger)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LedgerAccount(Base):
    __tablename__ = "ledger_account"
    __table_args__ = (
        CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_ledger_currency"),
        CheckConstraint("id = code || ':' || currency", name="ck_ledger_identifier"),
    )
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    code: Mapped[str] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(3))


class JournalEntry(Base):
    __tablename__ = "journal_entry"
    __table_args__ = (
        ForeignKeyConstraint(
            ["transaction_id", "amount_minor", "currency"],
            [
                "financial_transaction.id",
                "financial_transaction.amount_minor",
                "financial_transaction.currency",
            ],
            name="fk_journal_transaction_money",
        ),
        CheckConstraint("event_type IN ('CAPTURE','REVERSAL','SETTLEMENT')", name="ck_journal_event"),
        CheckConstraint("amount_minor > 0 AND amount_minor <= 1000000000000", name="ck_journal_amount"),
        CheckConstraint("debit_account_id <> credit_account_id", name="ck_journal_accounts"),
        CheckConstraint(
            "debit_account_id LIKE '%:' || currency AND credit_account_id LIKE '%:' || currency",
            name="ck_journal_currency",
        ),
        Index("ix_journal_transaction", "transaction_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("financial_transaction.id"))
    event_type: Mapped[str] = mapped_column(String(30))
    debit_account_id: Mapped[str] = mapped_column(ForeignKey("ledger_account.id"))
    credit_account_id: Mapped[str] = mapped_column(ForeignKey("ledger_account.id"))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


JournalEntry.__table__.append_constraint(
    UniqueConstraint("transaction_id", "event_type", name="uq_journal_event")
)
