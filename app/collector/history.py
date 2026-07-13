from __future__ import annotations

import logging
import hashlib
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient

from app.core.config import settings
from app.core.enums import CollectorSyncStatus
from app.collector.serialization import entity_chat_id, message_values, user_values
from app.database.repositories import (
    CollectorStateRepository,
    MediaJobRepository,
    MessageAnalysisJobRepository,
    MessageRepository,
    SourceRepository,
)
from app.database.session import SessionFactory
from app.database.models import TelegramChat

logger = logging.getLogger(__name__)


def message_is_within_history_window(message_date: datetime) -> bool:
    return message_date >= datetime.now(timezone.utc) - timedelta(
        days=settings.collector_history_days
    )


def image_metadata(message: object) -> tuple[str, str | None] | None:
    if getattr(message, "photo", None) is not None:
        return "photo", "image/jpeg"
    document = getattr(message, "document", None)
    mime_type = getattr(document, "mime_type", None)
    if isinstance(mime_type, str) and mime_type.startswith("image/"):
        return "image_document", mime_type
    return None


async def synchronize_history(
    client: TelegramClient, source: TelegramChat, *, force: bool = False
) -> int:
    """Load initial history or resume after the recorded Telegram message ID."""
    if source.telegram_chat_id is None:
        raise ValueError("Source has not been resolved to a Telegram chat ID")
    async with SessionFactory() as session:
        state_repository = CollectorStateRepository(session)
        current_state = await state_repository.get(source.telegram_chat_id)
    entity = await client.get_entity(source.telegram_chat_id or source.username)
    received = 0
    last_message_id = current_state.last_message_id if current_state else None
    is_resume = last_message_id is not None and not force
    limit = settings.collector_history_batch_size if is_resume else source.history_limit
    highest_id = last_message_id
    logger.info(
        "Starting %s sync for source %s", "incremental" if is_resume else "history", source.id
    )
    async for message in client.iter_messages(
        entity,
        limit=limit,
        min_id=last_message_id if is_resume else 0,
        reverse=is_resume,
    ):
        if not is_resume and source.collect_from_date and message.date < source.collect_from_date:
            break
        if not is_resume and not message_is_within_history_window(message.date):
            break
        if message_is_within_history_window(message.date):
            await persist_message(client, message, entity_chat_id(entity), edited=False)
        highest_id = max(highest_id or message.id, message.id)
        received += 1
    async with SessionFactory.begin() as session:
        await CollectorStateRepository(session).save_state(
            source.telegram_chat_id, last_message_id=highest_id, status=CollectorSyncStatus.SUCCESS
        )
        source_repository = SourceRepository(session)
        await source_repository.record_sync(source.id)
        await source_repository.clear_history_request(source.id)
    logger.info("Finished source %s sync: %s messages", source.id, received)
    return received


async def persist_message(
    client: TelegramClient, message: object, telegram_chat_id: int, *, edited: bool
) -> bool:
    """Persist one message in an isolated transaction, so malformed updates cannot stop collection."""
    if not message_is_within_history_window(message.date):  # type: ignore[attr-defined]
        return False
    sender = await message.get_sender()  # type: ignore[attr-defined]
    async with SessionFactory.begin() as session:
        repository = MessageRepository(session)
        sender_data = user_values(sender)
        if sender_data:
            await repository.upsert_user(sender_data)
        saved_message = await repository.upsert_message(
            message_values(message, telegram_chat_id), save_edit=edited
        )
        source_hash = hashlib.sha256((saved_message.text or "").encode("utf-8")).hexdigest()
        await MessageAnalysisJobRepository(session).enqueue(
            saved_message.id, source_hash, settings.text_analyzer_version
        )
        media = image_metadata(message)
        if media is not None:
            await MediaJobRepository(session).create_pending(
                saved_message.id, source_kind=media[0], original_mime_type=media[1]
            )
    return True
