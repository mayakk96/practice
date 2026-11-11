"""Transactional banking outbox and independent read projections.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "banking_outbox",
        sa.Column(
            "sequence",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("event_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_failure", sa.String(60)),
        sa.CheckConstraint("attempts >= 0", name="ck_banking_outbox_attempts"),
    )
    op.create_index(
        "ix_banking_outbox_pending", "banking_outbox", ["published_at", "available_at", "sequence"]
    )
    op.create_index("ix_banking_outbox_order", "banking_outbox", ["aggregate_id", "published_at", "sequence"])
    op.create_table(
        "banking_consumed_event",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("envelope_hash", sa.String(64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "banking_transaction_projection",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("transaction_type", sa.String(30), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "amount_minor > 0 AND amount_minor <= 1000000000000", name="ck_banking_projection_money"
        ),
        sa.CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_banking_projection_currency"),
        sa.CheckConstraint("version >= 0", name="ck_banking_projection_version"),
    )
    op.create_index(
        "ix_banking_projection_daily",
        "banking_transaction_projection",
        ["business_date", "currency", "status"],
    )
    op.create_table(
        "banking_settlement_projection",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("transaction_count", sa.Integer(), nullable=False),
        sa.Column("gross_debit_minor", sa.BigInteger(), nullable=False),
        sa.Column("gross_credit_minor", sa.BigInteger(), nullable=False),
        sa.Column("net_minor", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "currency IN ('USD','EUR','GBP')", name="ck_banking_settlement_projection_currency"
        ),
        sa.CheckConstraint(
            "transaction_count > 0 AND gross_debit_minor >= 0 AND gross_credit_minor >= 0",
            name="ck_banking_settlement_projection_totals",
        ),
        sa.CheckConstraint(
            "net_minor = gross_debit_minor - gross_credit_minor", name="ck_banking_settlement_projection_net"
        ),
        sa.CheckConstraint("version >= 0", name="ck_banking_settlement_projection_version"),
    )
    op.create_index(
        "ix_banking_settlement_projection_date",
        "banking_settlement_projection",
        ["business_date", "currency"],
    )
    op.create_table(
        "banking_exception_projection",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('OPEN','INVESTIGATING','RESOLVED')", name="ck_banking_exception_projection_status"
        ),
        sa.CheckConstraint("version >= 0", name="ck_banking_exception_projection_version"),
    )
    op.create_index(
        "ix_banking_exception_projection_status", "banking_exception_projection", ["status", "severity"]
    )
    op.create_table(
        "banking_reconciliation_projection",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("matched", sa.Integer(), nullable=False),
        sa.Column("unmatched", sa.Integer(), nullable=False),
        sa.Column("variance_minor", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_banking_recon_projection_currency"),
        sa.CheckConstraint(
            "matched >= 0 AND unmatched >= 0 AND version >= 0", name="ck_banking_recon_projection_counts"
        ),
    )


def downgrade():
    for table in (
        "banking_reconciliation_projection",
        "banking_exception_projection",
        "banking_settlement_projection",
        "banking_transaction_projection",
        "banking_consumed_event",
        "banking_outbox",
    ):
        op.drop_table(table)
