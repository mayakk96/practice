"""Immutable reconciliation evidence and audited operational exceptions.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "external_reconciliation_import",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("source_reference", sa.String(100), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("record_count BETWEEN 1 AND 1000", name="ck_external_import_count"),
    )
    op.create_table(
        "external_reconciliation_record",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("import_id", sa.Uuid(), sa.ForeignKey("external_reconciliation_import.id"), nullable=False),
        sa.Column("external_reference", sa.String(100), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("received_date", sa.Date(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "amount_minor <> 0 AND amount_minor BETWEEN -1000000000000 AND 1000000000000",
            name="ck_external_recon_amount",
        ),
        sa.CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_external_recon_currency"),
        sa.CheckConstraint("status IN ('SETTLED','CLEARED','FAILED')", name="ck_external_recon_status"),
        sa.CheckConstraint("received_date >= business_date", name="ck_external_recon_received_date"),
    )
    op.create_index(
        "ix_external_recon_date_currency_ref",
        "external_reconciliation_record",
        ["business_date", "currency", "external_reference"],
    )
    op.create_index(
        "ix_external_recon_reference",
        "external_reconciliation_record",
        ["external_reference", "business_date"],
    )
    op.create_table(
        "reconciliation_run",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("previous_run_id", sa.Uuid(), sa.ForeignKey("reconciliation_run.id"), nullable=True),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("records_processed", sa.Integer(), nullable=False),
        sa.Column("records_matched", sa.Integer(), nullable=False),
        sa.Column("records_unmatched", sa.Integer(), nullable=False),
        sa.Column("total_internal_minor", sa.BigInteger(), nullable=False),
        sa.Column("total_external_minor", sa.BigInteger(), nullable=False),
        sa.Column("variance_minor", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_recon_run_currency"),
        sa.CheckConstraint("status IN ('COMPLETED')", name="ck_recon_run_status"),
        sa.CheckConstraint(
            "records_processed = records_matched + records_unmatched", name="ck_recon_run_counts"
        ),
        sa.CheckConstraint(
            "records_processed >= 0 AND records_matched >= 0 AND records_unmatched >= 0",
            name="ck_recon_nonnegative_counts",
        ),
        sa.CheckConstraint(
            "variance_minor = total_internal_minor - total_external_minor", name="ck_recon_run_variance"
        ),
    )
    op.create_index(
        "ix_recon_run_business_date_currency",
        "reconciliation_run",
        ["business_date", "currency", "started_at"],
    )
    op.create_table(
        "reconciliation_result",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("reconciliation_run.id"), nullable=False),
        sa.Column("external_reference", sa.String(100), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("financial_transaction.id"), nullable=True),
        sa.Column("classifications", sa.String(400), nullable=False),
        sa.Column("internal_amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("external_amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("variance_minor", sa.BigInteger(), nullable=False),
        sa.Column("internal_status", sa.String(30), nullable=True),
        sa.Column("external_status", sa.String(30), nullable=True),
        sa.Column("internal_business_date", sa.Date(), nullable=True),
        sa.Column("external_business_date", sa.Date(), nullable=True),
        sa.Column("internal_version", sa.BigInteger(), nullable=True),
        sa.Column("external_record_ids", sa.Text(), nullable=False),
        sa.CheckConstraint("currency IN ('USD','EUR','GBP')", name="ck_recon_result_currency"),
        sa.UniqueConstraint("run_id", "external_reference", name="uq_recon_run_reference"),
    )
    op.create_table(
        "operational_exception",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("issue_key", sa.String(64), nullable=False, unique=True),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("financial_transaction.id"), nullable=True),
        sa.Column("reconciliation_run_id", sa.Uuid(), sa.ForeignKey("reconciliation_run.id"), nullable=False),
        sa.Column(
            "reconciliation_result_id", sa.Uuid(), sa.ForeignKey("reconciliation_result.id"), nullable=False
        ),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("assigned_team", sa.String(50), nullable=False),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('OPEN','INVESTIGATING','RESOLVED')", name="ck_operational_exception_status"
        ),
        sa.CheckConstraint("severity IN ('MEDIUM','HIGH')", name="ck_operational_exception_severity"),
        sa.CheckConstraint("version >= 0", name="ck_operational_exception_version"),
    )
    op.create_index("ix_exception_status_created", "operational_exception", ["status", "created_at", "id"])
    op.create_table(
        "operational_exception_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("exception_id", sa.Uuid(), sa.ForeignKey("operational_exception.id"), nullable=False),
        sa.Column("previous_status", sa.String(20), nullable=True),
        sa.Column("new_status", sa.String(20), nullable=False),
        sa.Column("assigned_team", sa.String(50), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("correlation_id", sa.String(100), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("exception_id", "version", name="uq_exception_history_version"),
    )


def downgrade():
    for table in (
        "operational_exception_history",
        "operational_exception",
        "reconciliation_result",
        "reconciliation_run",
        "external_reconciliation_record",
        "external_reconciliation_import",
    ):
        op.drop_table(table)
