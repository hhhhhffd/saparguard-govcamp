from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class SenderRead(BaseModel):
    telegram_user_id: int
    first_name: str | None
    last_name: str | None
    username: str | None


class ChatShortRead(BaseModel):
    telegram_chat_id: int | None
    title: str | None
    username: str | None
    chat_type: str


class MessageRead(BaseModel):
    id: int
    telegram_message_id: int
    text: str | None
    published_at: datetime
    saved_at: datetime
    is_forwarded: bool
    forward_source_id: int | None
    forward_source_name: str | None
    media_type: str | None
    edited_at: datetime | None
    is_deleted: bool
    deleted_at: datetime | None
    chat: ChatShortRead
    sender: SenderRead | None


class MessageEditRead(BaseModel):
    id: int
    previous_text: str | None
    detected_at: datetime


class PlateDetectionRead(BaseModel):
    raw_text: str
    normalized_text: str
    confidence: float | None


class MediaFileRead(BaseModel):
    id: int
    mime_type: str | None
    processing_status: str
    last_error: str | None
    plates: list[PlateDetectionRead]


class MessageDetailRead(MessageRead):
    edits: list[MessageEditRead]
    media_files: list[MediaFileRead]


class MessageCursor(BaseModel):
    sent_at: datetime
    id: int


class MessagePage(BaseModel):
    items: list[MessageRead]
    next_cursor: MessageCursor | None
    has_more: bool
