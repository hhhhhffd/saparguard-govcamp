from __future__ import annotations

import logging

from telethon import events

from app.collector.history import persist_message
from app.core.enums import CollectorSyncStatus
from app.database.repositories import CollectorStateRepository, MessageRepository, SourceRepository
from app.database.session import SessionFactory

logger = logging.getLogger(__name__)


async def is_active_chat(telegram_chat_id: int) -> bool:
    async with SessionFactory() as session:
        return await SourceRepository(session).is_active_chat(telegram_chat_id)


async def handle_new_message(event: events.NewMessage.Event) -> None:
    try:
        chat_id = event.chat_id
        if chat_id is None or not await is_active_chat(chat_id):
            return
        await persist_message(event.client, event.message, chat_id, edited=False)
        async with SessionFactory.begin() as session:
            await CollectorStateRepository(session).save_state(
                chat_id, last_message_id=event.message.id, status=CollectorSyncStatus.REALTIME
            )
            await SourceRepository(session).record_sync_for_chat(chat_id)
        logger.info("Saved new message %s in chat %s", event.message.id, chat_id)
    except Exception:
        logger.exception("Could not save a new Telegram message")


async def handle_edited_message(event: events.MessageEdited.Event) -> None:
    try:
        chat_id = event.chat_id
        if chat_id is None or not await is_active_chat(chat_id):
            return
        await persist_message(event.client, event.message, chat_id, edited=True)
        logger.info("Saved edit for message %s in chat %s", event.message.id, chat_id)
    except Exception:
        logger.exception("Could not save an edited Telegram message")


async def handle_deleted_message(event: events.MessageDeleted.Event) -> None:
    try:
        chat_id = event.chat_id
        if chat_id is None or not await is_active_chat(chat_id):
            return
        async with SessionFactory.begin() as session:
            count = await MessageRepository(session).mark_deleted(chat_id, event.deleted_ids)
        logger.info("Marked %s deleted messages in chat %s", count, chat_id)
    except Exception:
        logger.exception("Could not mark deleted Telegram messages")
