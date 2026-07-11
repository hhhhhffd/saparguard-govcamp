from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CollectorState


class CollectorRepository:
    """Tracks per-source synchronization progress and failures."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, telegram_chat_id: int) -> CollectorState | None:
        return await self._session.scalar(
            select(CollectorState).where(CollectorState.telegram_chat_id == telegram_chat_id)
        )

    async def save_state(
        self,
        telegram_chat_id: int,
        *,
        last_message_id: int | None,
        status: str,
        error: str | None = None,
    ) -> None:
        statement = insert(CollectorState).values(
            telegram_chat_id=telegram_chat_id,
            last_message_id=last_message_id,
            last_synced_at=datetime.now(timezone.utc),
            last_sync_status=status,
            last_error=error,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[CollectorState.telegram_chat_id],
            set_={
                "last_message_id": statement.excluded.last_message_id,
                "last_synced_at": statement.excluded.last_synced_at,
                "last_sync_status": statement.excluded.last_sync_status,
                "last_error": statement.excluded.last_error,
            },
        )
        await self._session.execute(statement)
        await self._session.commit()
