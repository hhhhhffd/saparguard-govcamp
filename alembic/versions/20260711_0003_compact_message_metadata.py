"""Remove redundant Telegram metadata and compact media records."""

from alembic import op
import sqlalchemy as sa

revision = "20260711_0003"
down_revision = "20260711_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("telegram_messages", sa.Column("forward_source_id", sa.BigInteger(), nullable=True))
    op.add_column("telegram_messages", sa.Column("forward_source_name", sa.String(length=512), nullable=True))
    op.drop_column("telegram_messages", "raw_data")
    op.drop_column("telegram_messages", "reply_to_message_id")
    op.drop_column("telegram_messages", "forward_source")
    op.drop_column("telegram_messages", "has_media")
    op.drop_column("telegram_messages", "views")
    op.drop_column("telegram_messages", "forwards")
    op.drop_column("telegram_users", "raw_data")
    op.drop_column("message_edits", "previous_raw_data")
    op.drop_column("media_files", "width")
    op.drop_column("media_files", "height")


def downgrade() -> None:
    op.add_column("media_files", sa.Column("height", sa.Integer(), nullable=True))
    op.add_column("media_files", sa.Column("width", sa.Integer(), nullable=True))
    op.add_column("message_edits", sa.Column("previous_raw_data", sa.JSON(), nullable=True))
    op.add_column("telegram_users", sa.Column("raw_data", sa.JSON(), nullable=True))
    op.add_column("telegram_messages", sa.Column("forwards", sa.Integer(), nullable=True))
    op.add_column("telegram_messages", sa.Column("views", sa.Integer(), nullable=True))
    op.add_column("telegram_messages", sa.Column("has_media", sa.Boolean(), nullable=True))
    op.add_column("telegram_messages", sa.Column("forward_source", sa.JSON(), nullable=True))
    op.add_column("telegram_messages", sa.Column("reply_to_message_id", sa.Integer(), nullable=True))
    op.add_column("telegram_messages", sa.Column("raw_data", sa.JSON(), nullable=True))
    op.drop_column("telegram_messages", "forward_source_name")
    op.drop_column("telegram_messages", "forward_source_id")
