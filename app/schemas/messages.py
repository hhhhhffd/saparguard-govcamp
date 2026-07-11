from __future__ import annotations

from datetime import datetime
from typing import Any

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
    telegram_chat_id: int
    telegram_message_id: int
    text: str | None
    published_at: datetime
    saved_at: datetime
    reply_to_message_id: int | None
    is_forwarded: bool
    forward_source: dict[str, Any] | None
    has_media: bool
    media_type: str | None
    views: int | None
    forwards: int | None
    edited_at: datetime | None
    is_deleted: bool
    deleted_at: datetime | None
    chat: ChatShortRead
    sender: SenderRead | None


class MessageDetailRead(MessageRead):
    raw_data: dict[str, Any]
    edits: list[MessageEditRead]


class MessageEditRead(BaseModel):
    id: int
    previous_text: str | None
    previous_raw_data: dict[str, Any]
    detected_at: datetime


class MessagePage(BaseModel):
    items: list[MessageRead]
    page: int
    page_size: int
    total: int
