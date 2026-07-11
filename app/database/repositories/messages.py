from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import MessageEdit, TelegramMessage, TelegramUser


class MessageRepository:
    """Stores Telegram messages idempotently and exposes filtered reads."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_user(self, values: dict[str, Any]) -> None:
        if values.get("telegram_user_id") is None:
            return
        statement = insert(TelegramUser).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[TelegramUser.telegram_user_id],
            set_={key: statement.excluded[key] for key in values if key != "telegram_user_id"},
        )
        await self._session.execute(statement)

    async def upsert_message(self, values: dict[str, Any], *, save_edit: bool) -> TelegramMessage:
        existing = await self._session.scalar(
            select(TelegramMessage).where(
                TelegramMessage.telegram_chat_id == values["telegram_chat_id"],
                TelegramMessage.telegram_message_id == values["telegram_message_id"],
            )
        )
        if save_edit and existing is not None:
            self._session.add(
                MessageEdit(
                    message_id=existing.id,
                    previous_text=existing.text,
                    previous_raw_data=existing.raw_data,
                    detected_at=datetime.now(timezone.utc),
                )
            )
        statement = insert(TelegramMessage).values(**values)
        statement = statement.on_conflict_do_update(
            constraint="uq_telegram_messages_telegram_chat_id",
            set_={key: statement.excluded[key] for key in values if key not in {"telegram_chat_id", "telegram_message_id", "saved_at"}},
        ).returning(TelegramMessage)
        message = (await self._session.execute(statement)).scalar_one()
        await self._session.commit()
        return message

    async def mark_deleted(self, telegram_chat_id: int, message_ids: list[int]) -> int:
        result = await self._session.execute(
            update(TelegramMessage)
            .where(
                TelegramMessage.telegram_chat_id == telegram_chat_id,
                TelegramMessage.telegram_message_id.in_(message_ids),
            )
            .values(is_deleted=True, deleted_at=datetime.now(timezone.utc))
        )
        await self._session.commit()
        return result.rowcount or 0

    async def get(self, message_id: int) -> TelegramMessage | None:
        result = await self._session.execute(
            select(TelegramMessage)
            .options(selectinload(TelegramMessage.chat), selectinload(TelegramMessage.sender), selectinload(TelegramMessage.edits))
            .where(TelegramMessage.id == message_id)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        query: str | None,
        chat_id: int | None,
        sender_id: int | None,
        date_from: datetime | None,
        date_to: datetime | None,
        has_media: bool | None,
    ) -> tuple[list[TelegramMessage], int]:
        filters = []
        if query:
            filters.append(TelegramMessage.text.ilike(f"%{query}%"))
        if chat_id is not None:
            filters.append(TelegramMessage.telegram_chat_id == chat_id)
        if sender_id is not None:
            filters.append(TelegramMessage.telegram_sender_id == sender_id)
        if date_from is not None:
            filters.append(TelegramMessage.published_at >= date_from)
        if date_to is not None:
            filters.append(TelegramMessage.published_at <= date_to)
        if has_media is not None:
            filters.append(TelegramMessage.has_media.is_(has_media))
        where_clause = and_(*filters) if filters else True
        result = await self._session.execute(
            select(TelegramMessage)
            .options(selectinload(TelegramMessage.chat), selectinload(TelegramMessage.sender))
            .where(where_clause)
            .order_by(TelegramMessage.published_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        total = await self._session.scalar(select(func.count(TelegramMessage.id)).where(where_clause))
        return list(result.scalars()), total or 0
