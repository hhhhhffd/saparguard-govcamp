"""Add durable message text analysis."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260714_0004"
down_revision = "20260711_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_analysis_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("telegram_messages.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("source_text_hash", sa.String(64), nullable=False),
        sa.Column("analyzer_version", sa.String(64), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_message_analysis_jobs_pending",
        "message_analysis_jobs",
        ["status", "next_retry_at", "created_at"],
    )
    op.create_table(
        "message_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("telegram_messages.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("message_type", sa.String(32), nullable=False),
        sa.Column("classification_confidence", sa.Float(), nullable=False),
        sa.Column("source_text_hash", sa.String(64), nullable=False),
        sa.Column("analyzer_version", sa.String(64), nullable=False),
        sa.Column("attributes", postgresql.JSONB(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "extracted_entities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "analysis_id", sa.Integer(), sa.ForeignKey("message_analyses.id"), nullable=False
        ),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("role", sa.String(32)),
        sa.Column("raw_value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("start_offset", sa.Integer()),
        sa.Column("end_offset", sa.Integer()),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_extracted_entities_type_normalized",
        "extracted_entities",
        ["entity_type", "normalized_value"],
    )
    op.create_table(
        "message_routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "analysis_id", sa.Integer(), sa.ForeignKey("message_analyses.id"), nullable=False
        ),
        sa.Column("raw_origin", sa.Text(), nullable=False),
        sa.Column("normalized_origin", sa.String(255), nullable=False),
        sa.Column("raw_destination", sa.Text(), nullable=False),
        sa.Column("normalized_destination", sa.String(255), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("message_routes")
    op.drop_index("ix_extracted_entities_type_normalized", table_name="extracted_entities")
    op.drop_table("extracted_entities")
    op.drop_table("message_analyses")
    op.drop_index("ix_message_analysis_jobs_pending", table_name="message_analysis_jobs")
    op.drop_table("message_analysis_jobs")
