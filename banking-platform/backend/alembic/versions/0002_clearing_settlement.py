"""Clearing imports, immutable membership and controlled settlement batches."""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clearing_record",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "transaction_id",
            sa.Uuid(),
            sa.ForeignKey("financial_transaction.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("network_reference", sa.String(100), nullable=False, unique=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_minor > 0 AND amount_minor <= 1000000000000", name="ck_clearing_amount"),
        sa.CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_clearing_currency"),
    )
    op.create_index("ix_clearing_business_date", "clearing_record", ["business_date", "currency", "id"])
    op.create_table(
        "clearing_import",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("content_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("file_name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("rows_received", sa.Integer(), nullable=False),
        sa.Column("accepted", sa.Integer(), nullable=False),
        sa.Column("rejected", sa.Integer(), nullable=False),
        sa.Column("duplicates", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('PROCESSING','COMPLETED')", name="ck_clearing_import_status"),
        sa.CheckConstraint(
            "rows_received >= 0 AND accepted >= 0 AND rejected >= 0 AND duplicates >= 0",
            name="ck_clearing_import_counts",
        ),
    )
    op.create_table(
        "clearing_import_row",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("import_id", sa.Uuid(), sa.ForeignKey("clearing_import.id"), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("clearing_record_id", sa.Uuid(), sa.ForeignKey("clearing_record.id")),
        sa.UniqueConstraint("import_id", "row_number", name="uq_clearing_import_row"),
        sa.CheckConstraint("row_number > 0", name="ck_clearing_row_number"),
        sa.CheckConstraint("status IN ('ACCEPTED','REJECTED','DUPLICATE')", name="ck_clearing_row_status"),
    )
    op.create_table(
        "settlement_batch",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("transaction_count", sa.Integer(), nullable=False),
        sa.Column("gross_debit_minor", sa.BigInteger(), nullable=False),
        sa.Column("gross_credit_minor", sa.BigInteger(), nullable=False),
        sa.Column("net_minor", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_settlement_currency"),
        sa.CheckConstraint(
            "status IN ('OPEN','READY','SUBMITTED','CONFIRMED','RECONCILED')", name="ck_settlement_status"
        ),
        sa.CheckConstraint("transaction_count > 0 AND transaction_count <= 1000", name="ck_settlement_count"),
        sa.CheckConstraint("gross_debit_minor >= 0 AND gross_credit_minor >= 0", name="ck_settlement_gross"),
        sa.CheckConstraint("net_minor = gross_debit_minor - gross_credit_minor", name="ck_settlement_net"),
        sa.CheckConstraint("version >= 0", name="ck_settlement_version"),
    )
    op.create_index("ix_settlement_status_date", "settlement_batch", ["status", "business_date", "id"])
    op.create_table(
        "settlement_item",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("batch_id", sa.Uuid(), sa.ForeignKey("settlement_batch.id"), nullable=False),
        sa.Column(
            "transaction_id",
            sa.Uuid(),
            sa.ForeignKey("financial_transaction.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.CheckConstraint(
            "amount_minor > 0 AND amount_minor <= 1000000000000", name="ck_settlement_item_amount"
        ),
        sa.CheckConstraint("direction IN ('DEBIT','CREDIT')", name="ck_settlement_item_direction"),
    )
    op.create_index("ix_settlement_items_batch", "settlement_item", ["batch_id", "id"])
    op.create_table(
        "settlement_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("batch_id", sa.Uuid(), sa.ForeignKey("settlement_batch.id"), nullable=False),
        sa.Column("previous_status", sa.String(20)),
        sa.Column("new_status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("correlation_id", sa.String(100), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("batch_version", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("batch_id", "batch_version", name="uq_settlement_history_version"),
    )


def downgrade():
    for table in (
        "settlement_history",
        "settlement_item",
        "settlement_batch",
        "clearing_import_row",
        "clearing_import",
        "clearing_record",
    ):
        op.drop_table(table)
