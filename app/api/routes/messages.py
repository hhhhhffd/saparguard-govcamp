from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import TelegramMessage
from app.database.repositories import MessageRepository
from app.database.session import get_session
from app.schemas.messages import ChatShortRead, MessageDetailRead, MessageEditRead, MessagePage, MessageRead, SenderRead

router = APIRouter(prefix="/messages", tags=["messages"])


def serialize_message(message: TelegramMessage, include_details: bool = False) -> MessageRead | MessageDetailRead:
    data: dict[str, Any] = {
        "id": message.id,
        "telegram_chat_id": message.telegram_chat_id,
        "telegram_message_id": message.telegram_message_id,
        "text": message.text,
        "published_at": message.published_at,
        "saved_at": message.saved_at,
        "reply_to_message_id": message.reply_to_message_id,
        "is_forwarded": message.is_forwarded,
        "forward_source": message.forward_source,
        "has_media": message.has_media,
        "media_type": message.media_type,
        "views": message.views,
        "forwards": message.forwards,
        "edited_at": message.edited_at,
        "is_deleted": message.is_deleted,
        "deleted_at": message.deleted_at,
        "chat": ChatShortRead(
            telegram_chat_id=message.chat.telegram_chat_id,
            title=message.chat.title,
            username=message.chat.username,
            chat_type=message.chat.chat_type,
        ),
        "sender": (
            SenderRead(
                telegram_user_id=message.sender.telegram_user_id,
                first_name=message.sender.first_name,
                last_name=message.sender.last_name,
                username=message.sender.username,
            )
            if message.sender
            else None
        ),
    }
    if include_details:
        data["raw_data"] = message.raw_data
        data["edits"] = [
            MessageEditRead(
                id=edit.id,
                previous_text=edit.previous_text,
                previous_raw_data=edit.previous_raw_data,
                detected_at=edit.detected_at,
            )
            for edit in message.edits
        ]
        return MessageDetailRead(**data)
    return MessageRead(**data)


@router.get("", response_model=MessagePage)
async def list_messages(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    query: str | None = None,
    chat_id: int | None = None,
    sender_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    has_media: bool | None = None,
    session: AsyncSession = Depends(get_session),
) -> MessagePage:
    messages, total = await MessageRepository(session).list(
        page=page,
        page_size=page_size,
        query=query,
        chat_id=chat_id,
        sender_id=sender_id,
        date_from=date_from,
        date_to=date_to,
        has_media=has_media,
    )
    return MessagePage(items=[serialize_message(item) for item in messages], page=page, page_size=page_size, total=total)


@router.get("/{message_id}", response_model=MessageDetailRead)
async def get_message(message_id: int, session: AsyncSession = Depends(get_session)) -> MessageDetailRead:
    message = await MessageRepository(session).get(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return serialize_message(message, include_details=True)
