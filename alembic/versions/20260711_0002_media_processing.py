"""Add persistent media processing and plate detection tables."""

from alembic import op
import sqlalchemy as sa

revision = "20260711_0002"
down_revision = "20260711_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("original_mime_type", sa.String(length=255), nullable=True),
        sa.Column("relative_path", sa.String(length=512), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("processing_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["message_id"], ["telegram_messages.id"]),
        sa.UniqueConstraint("message_id", name="uq_media_files_message_id"),
    )
    op.create_index("ix_media_files_message_id", "media_files", ["message_id"])
    op.create_index("ix_media_files_sha256", "media_files", ["sha256"])
    op.create_table(
        "media_processing_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("media_file_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["message_id"], ["telegram_messages.id"]),
        sa.ForeignKeyConstraint(["media_file_id"], ["media_files.id"]),
        sa.UniqueConstraint("media_file_id", name="uq_media_processing_jobs_media_file_id"),
    )
    op.create_index("ix_media_processing_jobs_message_id", "media_processing_jobs", ["message_id"])
    op.create_index("ix_media_processing_jobs_media_file_id", "media_processing_jobs", ["media_file_id"])
    op.create_index("ix_media_processing_jobs_status", "media_processing_jobs", ["status"])
    op.create_index("ix_media_processing_jobs_next_retry_at", "media_processing_jobs", ["next_retry_at"])
    op.create_table(
        "plate_detections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("media_file_id", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.String(length=128), nullable=False),
        sa.Column("normalized_text", sa.String(length=128), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("bbox_x1", sa.Float(), nullable=False),
        sa.Column("bbox_y1", sa.Float(), nullable=False),
        sa.Column("bbox_x2", sa.Float(), nullable=False),
        sa.Column("bbox_y2", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["media_file_id"], ["media_files.id"]),
    )
    op.create_index("ix_plate_detections_media_file_id", "plate_detections", ["media_file_id"])
    op.create_index("ix_plate_detections_normalized_text", "plate_detections", ["normalized_text"])
    op.create_index(
        "ix_telegram_messages_published_at_id",
        "telegram_messages",
        [sa.text("published_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_messages_published_at_id", table_name="telegram_messages")
    op.drop_table("plate_detections")
    op.drop_table("media_processing_jobs")
    op.drop_table("media_files")
