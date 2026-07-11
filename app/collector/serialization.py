from __future__ import annotations

from datetime import datetime
from typing import Any

from telethon.tl import types
from telethon.utils import get_peer_id


def chat_type(entity: Any) -> str:
    if isinstance(entity, types.Channel):
        return "channel" if entity.broadcast else "supergroup"
    if isinstance(entity, types.Chat):
        return "group"
    return "unknown"


def entity_chat_id(entity: Any) -> int:
    return get_peer_id(entity)


def media_type(message: Any) -> str | None:
    if message.media is None:
        return None
    return type(message.media).__name__.removeprefix("MessageMedia") or "unknown"


def user_values(sender: Any) -> dict[str, Any] | None:
    if not isinstance(sender, types.User):
        return None
    return {
        "telegram_user_id": sender.id,
        "first_name": sender.first_name,
        "last_name": sender.last_name,
        "username": sender.username,
        "updated_at": datetime.now().astimezone(),
    }


def message_values(message: Any, telegram_chat_id: int) -> dict[str, Any]:
    forward = getattr(message, "fwd_from", None)
    forward_peer = getattr(forward, "from_id", None) if forward else None
    forward_id = get_peer_id(forward_peer) if forward_peer else None
    return {
        "telegram_chat_id": telegram_chat_id,
        "telegram_message_id": message.id,
        "telegram_sender_id": message.sender_id,
        "text": message.message,
        "published_at": message.date,
        "saved_at": datetime.now().astimezone(),
        "is_forwarded": forward is not None,
        "forward_source_id": forward_id,
        "forward_source_name": (
            getattr(forward, "from_name", None) or getattr(forward, "post_author", None)
            if forward
            else None
        ),
        "media_type": media_type(message),
        "edited_at": message.edit_date,
        "is_deleted": False,
        "deleted_at": None,
    }
