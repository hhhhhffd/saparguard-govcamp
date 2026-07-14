from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base

if TYPE_CHECKING:
    from app.database.models.media import MediaFile
    from app.database.models.analysis import MessageAnalysis, MessageAnalysisJob
    from app.database.models.review import MessageAnnotation


class TelegramChat(Base):
    __tablename__ = "telegram_chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(
        BigInteger, unique=True, index=True, nullable=True
    )
    username: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    chat_type: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    load_history: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    history_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    collect_from_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    history_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list[TelegramMessage]] = relationship(back_populates="chat")


class TelegramUser(Base):
    __tablename__ = "telegram_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    messages: Mapped[list[TelegramMessage]] = relationship(back_populates="sender")


class TelegramMessage(Base):
    __tablename__ = "telegram_messages"
    __table_args__ = (UniqueConstraint("telegram_chat_id", "telegram_message_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("telegram_chats.telegram_chat_id"), index=True, nullable=False
    )
    telegram_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    telegram_sender_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("telegram_users.telegram_user_id"), nullable=True, index=True
    )
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_forwarded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    forward_source_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    forward_source_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    chat: Mapped[TelegramChat] = relationship(back_populates="messages")
    sender: Mapped[TelegramUser | None] = relationship(back_populates="messages")
    edits: Mapped[list[MessageEdit]] = relationship(back_populates="message")
    media_files: Mapped[list["MediaFile"]] = relationship(back_populates="message")
    analysis: Mapped["MessageAnalysis | None"] = relationship(back_populates="message")
    analysis_job: Mapped["MessageAnalysisJob | None"] = relationship(back_populates="message")
    annotation: Mapped["MessageAnnotation | None"] = relationship(back_populates="message")


class MessageEdit(Base):
    __tablename__ = "message_edits"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("telegram_messages.id"), index=True)
    previous_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    message: Mapped[TelegramMessage] = relationship(back_populates="edits")


class CollectorState(Base):
    __tablename__ = "collector_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("telegram_chats.telegram_chat_id"), unique=True, index=True
    )
    last_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
