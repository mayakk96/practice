"""Frozen account, transaction, idempotency and structurally balanced ledger schema."""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    uuid = sa.Uuid()
    ts = sa.DateTime(timezone=True)
    op.create_table(
        "customer",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("external_reference", sa.String(100), nullable=False, unique=True),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", ts, nullable=False),
    )
    op.create_table(
        "bank_account",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("customer_id", uuid, sa.ForeignKey("customer.id"), nullable=False),
        sa.Column("account_reference", sa.String(100), nullable=False, unique=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", ts, nullable=False),
        sa.Column("updated_at", ts, nullable=False),
        sa.CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_account_currency"),
        sa.CheckConstraint("status IN ('ACTIVE','BLOCKED','CLOSED')", name="ck_account_status"),
    )
    op.create_index("ix_account_customer", "bank_account", ["customer_id"])
    op.create_table(
        "financial_transaction",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("external_reference", sa.String(100), nullable=False, unique=True),
        sa.Column("transaction_type", sa.String(30), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("source_account_id", uuid, sa.ForeignKey("bank_account.id"), nullable=False),
        sa.Column("counterparty_reference", sa.String(100), nullable=False),
        sa.Column("original_transaction_id", uuid, sa.ForeignKey("financial_transaction.id"), unique=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("network_reference", sa.String(100)),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("created_at", ts, nullable=False),
        sa.Column("updated_at", ts, nullable=False),
        sa.UniqueConstraint("id", "amount_minor", "currency", name="uq_tx_money"),
        sa.CheckConstraint("amount_minor > 0 AND amount_minor <= 1000000000000", name="ck_tx_amount"),
        sa.CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_tx_currency"),
        sa.CheckConstraint(
            "transaction_type IN ('CARD_PURCHASE','ACCOUNT_TRANSFER','REFUND')", name="ck_tx_type"
        ),
        sa.CheckConstraint(
            "status IN ('RECEIVED','VALIDATED','AUTHORIZED','DECLINED','CAPTURED','CLEARED','SETTLED','REVERSED','REFUNDED')",
            name="ck_tx_status",
        ),
    )
    op.create_index("ix_tx_status_date", "financial_transaction", ["status", "business_date", "id"])
    op.create_index("ix_tx_account_time", "financial_transaction", ["source_account_id", "created_at", "id"])
    op.create_table(
        "transaction_idempotency",
        sa.Column("request_key", sa.String(100), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("transaction_id", uuid, sa.ForeignKey("financial_transaction.id")),
        sa.Column("response_json", sa.String(8000)),
        sa.Column("created_at", ts, nullable=False),
    )
    op.create_table(
        "transaction_history",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("transaction_id", uuid, sa.ForeignKey("financial_transaction.id"), nullable=False),
        sa.Column("previous_status", sa.String(30)),
        sa.Column("new_status", sa.String(30), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("changed_at", ts, nullable=False),
        sa.UniqueConstraint("transaction_id", "version", name="uq_history_version"),
    )
    op.create_table(
        "ledger_account",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_ledger_currency"),
        sa.CheckConstraint("id = code || ':' || currency", name="ck_ledger_identifier"),
    )
    for currency in ("USD", "EUR", "GBP"):
        for code in ("CUSTOMER_RECEIVABLE", "NETWORK_PAYABLE", "CASH_CLEARING"):
            op.execute(
                sa.text(
                    "INSERT INTO ledger_account(id,code,currency) VALUES (:id,:code,:currency)"
                ).bindparams(id=f"{code}:{currency}", code=code, currency=currency)
            )
    op.create_table(
        "journal_entry",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("transaction_id", uuid, sa.ForeignKey("financial_transaction.id"), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("debit_account_id", sa.String(80), sa.ForeignKey("ledger_account.id"), nullable=False),
        sa.Column("credit_account_id", sa.String(80), sa.ForeignKey("ledger_account.id"), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("created_at", ts, nullable=False),
        sa.ForeignKeyConstraint(
            ["transaction_id", "amount_minor", "currency"],
            [
                "financial_transaction.id",
                "financial_transaction.amount_minor",
                "financial_transaction.currency",
            ],
            name="fk_journal_transaction_money",
        ),
        sa.CheckConstraint("event_type IN ('CAPTURE','REVERSAL','SETTLEMENT')", name="ck_journal_event"),
        sa.CheckConstraint("amount_minor > 0 AND amount_minor <= 1000000000000", name="ck_journal_amount"),
        sa.CheckConstraint("debit_account_id <> credit_account_id", name="ck_journal_accounts"),
        sa.CheckConstraint(
            "debit_account_id LIKE '%:' || currency AND credit_account_id LIKE '%:' || currency",
            name="ck_journal_currency",
        ),
        sa.UniqueConstraint("transaction_id", "event_type", name="uq_journal_event"),
    )
    op.create_index("ix_journal_transaction", "journal_entry", ["transaction_id", "created_at"])
    op.execute(
        "CREATE VIEW ledger_posting AS SELECT id AS journal_id, transaction_id, debit_account_id AS account_id, 'DEBIT' AS side, amount_minor,currency,created_at FROM journal_entry UNION ALL SELECT id AS journal_id,transaction_id,credit_account_id AS account_id,'CREDIT' AS side,amount_minor,currency,created_at FROM journal_entry"
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE FUNCTION forbid_journal_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'journal entries are immutable'; END $$"
        )
        op.execute(
            "CREATE TRIGGER immutable_journal BEFORE UPDATE OR DELETE ON journal_entry FOR EACH ROW EXECUTE FUNCTION forbid_journal_mutation()"
        )
    else:
        op.execute(
            "CREATE TRIGGER immutable_journal_update BEFORE UPDATE ON journal_entry BEGIN SELECT RAISE(ABORT,'journal entries are immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER immutable_journal_delete BEFORE DELETE ON journal_entry BEGIN SELECT RAISE(ABORT,'journal entries are immutable'); END"
        )


def downgrade():
    op.execute("DROP VIEW ledger_posting")
    op.drop_table("journal_entry")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION forbid_journal_mutation()")
    for table in (
        "ledger_account",
        "transaction_history",
        "transaction_idempotency",
        "financial_transaction",
        "bank_account",
        "customer",
    ):
        op.drop_table(table)
