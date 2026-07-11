from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import TelegramChat, TelegramMessage


class SourceRepository:
    """Persistence operations for configured Telegram sources."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> list[tuple[TelegramChat, int, datetime | None]]:
        result = await self._session.execute(
            select(
                TelegramChat,
                func.count(TelegramMessage.id).label("message_count"),
                func.max(TelegramMessage.published_at).label("last_message_at"),
            )
            .outerjoin(TelegramMessage, TelegramMessage.telegram_chat_id == TelegramChat.telegram_chat_id)
            .where(TelegramChat.removed_at.is_(None))
            .group_by(TelegramChat.id)
            .order_by(TelegramChat.created_at.desc())
        )
        return [(row[0], row[1], row[2]) for row in result.all()]

    async def get(self, source_id: int) -> TelegramChat | None:
        return await self._session.get(TelegramChat, source_id)

    async def get_active(self) -> list[TelegramChat]:
        result = await self._session.scalars(
            select(TelegramChat).where(TelegramChat.is_active.is_(True), TelegramChat.removed_at.is_(None))
        )
        return list(result)

    async def create(
        self,
        *,
        telegram_chat_id: int | None,
        username: str | None,
        title: str | None,
        load_history: bool,
        history_limit: int | None,
        collect_from_date: datetime | None,
    ) -> TelegramChat:
        source = TelegramChat(
            telegram_chat_id=telegram_chat_id,
            username=username,
            title=title,
            chat_type="unknown",
            load_history=load_history,
            history_limit=history_limit,
            collect_from_date=collect_from_date,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(source)
        await self._session.commit()
        await self._session.refresh(source)
        return source

    async def update_resolved(
        self,
        source_id: int,
        *,
        telegram_chat_id: int,
        username: str | None,
        title: str | None,
        chat_type: str,
    ) -> None:
        await self._session.execute(
            update(TelegramChat)
            .where(TelegramChat.id == source_id)
            .values(
                telegram_chat_id=telegram_chat_id,
                username=username,
                title=title,
                chat_type=chat_type,
                updated_at=datetime.now(timezone.utc),
                last_error=None,
            )
        )
        await self._session.commit()

    async def set_active(self, source_id: int, is_active: bool) -> TelegramChat | None:
        source = await self.get(source_id)
        if source is None:
            return None
        source.is_active = is_active
        source.updated_at = datetime.now(timezone.utc)
        await self._session.commit()
        await self._session.refresh(source)
        return source

    async def remove(self, source_id: int) -> bool:
        source = await self.get(source_id)
        if source is None:
            return False
        source.is_active = False
        source.removed_at = datetime.now(timezone.utc)
        await self._session.commit()
        return True

    async def request_history(self, source_id: int) -> TelegramChat | None:
        source = await self.get(source_id)
        if source is None:
            return None
        source.history_requested_at = datetime.now(timezone.utc)
        await self._session.commit()
        await self._session.refresh(source)
        return source

    async def clear_history_request(self, source_id: int) -> None:
        await self._session.execute(
            update(TelegramChat)
            .where(TelegramChat.id == source_id)
            .values(history_requested_at=None, updated_at=datetime.now(timezone.utc))
        )
        await self._session.commit()

    async def record_sync(self, source_id: int) -> None:
        await self._session.execute(
            update(TelegramChat)
            .where(TelegramChat.id == source_id)
            .values(last_synced_at=datetime.now(timezone.utc), last_error=None, updated_at=datetime.now(timezone.utc))
        )
        await self._session.commit()

    async def record_sync_for_chat(self, telegram_chat_id: int) -> None:
        await self._session.execute(
            update(TelegramChat)
            .where(TelegramChat.telegram_chat_id == telegram_chat_id)
            .values(last_synced_at=datetime.now(timezone.utc), last_error=None, updated_at=datetime.now(timezone.utc))
        )
        await self._session.commit()

    async def record_error(self, source_id: int, error: str) -> None:
        await self._session.execute(
            update(TelegramChat)
            .where(TelegramChat.id == source_id)
            .values(last_error=error, updated_at=datetime.now(timezone.utc))
        )
        await self._session.commit()
