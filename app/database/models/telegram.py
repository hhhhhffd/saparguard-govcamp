from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base


class TelegramChat(Base):
    __tablename__ = "telegram_chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True, nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    chat_type: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    load_history: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    history_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    collect_from_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    history_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
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
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reply_to_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_forwarded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    forward_source: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    has_media: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forwards: Mapped[int | None] = mapped_column(Integer, nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    chat: Mapped[TelegramChat] = relationship(back_populates="messages")
    sender: Mapped[TelegramUser | None] = relationship(back_populates="messages")
    edits: Mapped[list[MessageEdit]] = relationship(back_populates="message")
    media_files: Mapped[list[MediaFile]] = relationship(back_populates="message")


class MessageEdit(Base):
    __tablename__ = "message_edits"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("telegram_messages.id"), index=True)
    previous_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
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


class MediaFile(Base):
    __tablename__ = "media_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("telegram_messages.id"), unique=True, index=True)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    original_mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    relative_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    message: Mapped[TelegramMessage] = relationship(back_populates="media_files")
    jobs: Mapped[list[MediaProcessingJob]] = relationship(back_populates="media_file")
    plate_detections: Mapped[list[PlateDetection]] = relationship(back_populates="media_file")


class MediaProcessingJob(Base):
    __tablename__ = "media_processing_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("telegram_messages.id"), index=True)
    media_file_id: Mapped[int] = mapped_column(ForeignKey("media_files.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    media_file: Mapped[MediaFile] = relationship(back_populates="jobs")


class PlateDetection(Base):
    __tablename__ = "plate_detections"

    id: Mapped[int] = mapped_column(primary_key=True)
    media_file_id: Mapped[int] = mapped_column(ForeignKey("media_files.id"), index=True)
    raw_text: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_text: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_x1: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_y1: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_x2: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_y2: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    media_file: Mapped[MediaFile] = relationship(back_populates="plate_detections")
