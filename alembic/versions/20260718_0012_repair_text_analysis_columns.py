"""Repair durable text-analysis columns omitted from an existing runtime schema."""

from alembic import op


revision = "20260718_0012"
down_revision = "20260717_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add columns idempotently so an incorrectly recorded revision can recover safely."""
    op.execute(
        "ALTER TABLE message_analysis_jobs "
        "ADD COLUMN IF NOT EXISTS lease_token VARCHAR(36)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_message_analysis_jobs_lease_token "
        "ON message_analysis_jobs (lease_token)"
    )
    op.execute(
        "ALTER TABLE message_analyses "
        "ADD COLUMN IF NOT EXISTS classification_evidence JSONB"
    )
    op.execute(
        "UPDATE message_analyses "
        "SET classification_evidence = '[]'::jsonb "
        "WHERE classification_evidence IS NULL"
    )
    op.execute(
        "ALTER TABLE message_analyses "
        "ALTER COLUMN classification_evidence SET NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_message_analysis_jobs_lease_token", table_name="message_analysis_jobs")
    op.drop_column("message_analysis_jobs", "lease_token")
    op.drop_column("message_analyses", "classification_evidence")
