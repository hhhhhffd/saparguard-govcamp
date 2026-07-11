from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from telethon.tl import types
from telethon.utils import get_peer_id


def to_jsonable(value: Any) -> Any:
    """Convert Telethon objects to JSONB-safe values while retaining their metadata."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return {"type": "bytes", "length": len(value)}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "to_dict"):
        return to_jsonable(value.to_dict())
    return str(value)


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
        "raw_data": to_jsonable(sender),
        "updated_at": datetime.now().astimezone(),
    }


def message_values(message: Any, telegram_chat_id: int) -> dict[str, Any]:
    forward = getattr(message, "fwd_from", None)
    reply_to = getattr(message, "reply_to", None)
    return {
        "telegram_chat_id": telegram_chat_id,
        "telegram_message_id": message.id,
        "telegram_sender_id": message.sender_id,
        "text": message.message,
        "published_at": message.date,
        "saved_at": datetime.now().astimezone(),
        "reply_to_message_id": getattr(reply_to, "reply_to_msg_id", None),
        "is_forwarded": forward is not None,
        "forward_source": to_jsonable(forward) if forward else None,
        "has_media": message.media is not None,
        "media_type": media_type(message),
        "views": message.views,
        "forwards": message.forwards,
        "edited_at": message.edit_date,
        "is_deleted": False,
        "deleted_at": None,
        "raw_data": to_jsonable(message),
    }
