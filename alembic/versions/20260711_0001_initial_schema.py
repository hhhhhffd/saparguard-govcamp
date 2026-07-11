"""Create Telegram collector schema."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260711_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_chats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("chat_type", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("load_history", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("history_limit", sa.Integer(), nullable=True),
        sa.Column("collect_from_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("history_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("telegram_chat_id", name="uq_telegram_chats_telegram_chat_id"),
    )
    op.create_index("ix_telegram_chats_telegram_chat_id", "telegram_chats", ["telegram_chat_id"])
    op.create_index("ix_telegram_chats_username", "telegram_chats", ["username"])
    op.create_table(
        "telegram_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("telegram_user_id", name="uq_telegram_users_telegram_user_id"),
    )
    op.create_index("ix_telegram_users_telegram_user_id", "telegram_users", ["telegram_user_id"])
    op.create_index("ix_telegram_users_username", "telegram_users", ["username"])
    op.create_table(
        "telegram_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=False),
        sa.Column("telegram_sender_id", sa.BigInteger(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reply_to_message_id", sa.Integer(), nullable=True),
        sa.Column("is_forwarded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("forward_source", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("has_media", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("media_type", sa.String(length=64), nullable=True),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("forwards", sa.Integer(), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["telegram_chat_id"], ["telegram_chats.telegram_chat_id"]),
        sa.ForeignKeyConstraint(["telegram_sender_id"], ["telegram_users.telegram_user_id"]),
        sa.UniqueConstraint(
            "telegram_chat_id", "telegram_message_id", name="uq_telegram_messages_telegram_chat_id"
        ),
    )
    op.create_index(
        "ix_telegram_messages_telegram_chat_id", "telegram_messages", ["telegram_chat_id"]
    )
    op.create_index(
        "ix_telegram_messages_telegram_sender_id", "telegram_messages", ["telegram_sender_id"]
    )
    op.create_index("ix_telegram_messages_published_at", "telegram_messages", ["published_at"])
    op.create_index("ix_telegram_messages_is_deleted", "telegram_messages", ["is_deleted"])
    op.create_table(
        "message_edits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("previous_text", sa.Text(), nullable=True),
        sa.Column("previous_raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["telegram_messages.id"]),
    )
    op.create_index("ix_message_edits_message_id", "message_edits", ["message_id"])
    op.create_table(
        "collector_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("last_message_id", sa.Integer(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["telegram_chat_id"], ["telegram_chats.telegram_chat_id"]),
        sa.UniqueConstraint("telegram_chat_id", name="uq_collector_state_telegram_chat_id"),
    )
    op.create_index("ix_collector_state_telegram_chat_id", "collector_state", ["telegram_chat_id"])


def downgrade() -> None:
    op.drop_table("collector_state")
    op.drop_table("message_edits")
    op.drop_table("telegram_messages")
    op.drop_table("telegram_users")
    op.drop_table("telegram_chats")
