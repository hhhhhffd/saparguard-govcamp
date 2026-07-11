from __future__ import annotations

import logging

from telethon import TelegramClient
from telethon.errors import FloodWaitError

from app.collector.history import synchronize_history
from app.collector.serialization import chat_type, entity_chat_id
from app.core.enums import CollectorSyncStatus
from app.database.repositories import CollectorStateRepository, SourceRepository
from app.database.session import SessionFactory

logger = logging.getLogger(__name__)


async def resolve_source(client: TelegramClient, source_id: int) -> bool:
    """Resolve username or configured ID, retaining a helpful error on inaccessible chats."""
    async with SessionFactory() as session:
        source = await SourceRepository(session).get(source_id)
        if source is None:
            return False
        identifier = (
            source.telegram_chat_id if source.telegram_chat_id is not None else source.username
        )
    if identifier is None:
        return False
    try:
        # Numeric IDs need an access hash from the account's known dialogs.
        if isinstance(identifier, int) and source.title is None:
            await client.get_dialogs()
        entity = await client.get_entity(identifier)
        async with SessionFactory.begin() as session:
            await SourceRepository(session).update_resolved(
                source_id,
                telegram_chat_id=entity_chat_id(entity),
                username=getattr(entity, "username", None),
                title=getattr(entity, "title", None),
                chat_type=chat_type(entity),
            )
        return True
    except FloodWaitError:
        raise
    except Exception as exc:
        logger.exception("Could not resolve source %s", source_id)
        async with SessionFactory() as session:
            await SourceRepository(session).record_error(source_id, str(exc))
        return False


async def synchronize_configured_sources(
    client: TelegramClient, *, synchronize_existing: bool
) -> None:
    """Resolve sources and synchronize initial, requested, or restart-recovery history."""
    async with SessionFactory() as session:
        sources = await SourceRepository(session).get_active()
    for source in sources:
        try:
            if not await resolve_source(client, source.id):
                continue
            async with SessionFactory() as session:
                refreshed = await SourceRepository(session).get(source.id)
                state = (
                    await CollectorStateRepository(session).get(refreshed.telegram_chat_id)
                    if refreshed and refreshed.telegram_chat_id is not None
                    else None
                )
            is_initial_sync = state is None
            is_requested = refreshed is not None and refreshed.history_requested_at is not None
            can_load_initial = refreshed is not None and refreshed.load_history
            if refreshed and (
                is_requested
                or (is_initial_sync and can_load_initial)
                or (synchronize_existing and state)
            ):
                await synchronize_history(
                    client, refreshed, force=refreshed.history_requested_at is not None
                )
        except FloodWaitError as exc:
            logger.warning("Flood wait for source %s: %s seconds", source.id, exc.seconds)
            raise
        except Exception as exc:
            logger.exception("Synchronization failed for source %s", source.id)
            async with SessionFactory.begin() as session:
                await SourceRepository(session).record_error(source.id, str(exc))
                if source.telegram_chat_id is not None:
                    await CollectorStateRepository(session).save_state(
                        source.telegram_chat_id,
                        last_message_id=None,
                        status=CollectorSyncStatus.ERROR,
                        error=str(exc),
                    )
