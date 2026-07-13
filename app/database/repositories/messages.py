from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    ExtractedEntity,
    MediaFile,
    MessageAnalysis,
    MessageAnalysisJob,
    MessageEdit,
    TelegramMessage,
    TelegramUser,
)


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
                    detected_at=datetime.now(timezone.utc),
                )
            )
        statement = insert(TelegramMessage).values(**values)
        statement = statement.on_conflict_do_update(
            constraint="uq_telegram_messages_telegram_chat_id",
            set_={
                key: statement.excluded[key]
                for key in values
                if key not in {"telegram_chat_id", "telegram_message_id", "saved_at"}
            },
        ).returning(TelegramMessage)
        message = (await self._session.execute(statement)).scalar_one()
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
        return result.rowcount or 0

    async def get(self, message_id: int) -> TelegramMessage | None:
        result = await self._session.execute(
            select(TelegramMessage)
            .options(
                selectinload(TelegramMessage.chat),
                selectinload(TelegramMessage.sender),
                selectinload(TelegramMessage.edits),
                selectinload(TelegramMessage.media_files).selectinload(MediaFile.jobs),
                selectinload(TelegramMessage.media_files).selectinload(MediaFile.plate_detections),
                selectinload(TelegramMessage.analysis).selectinload(MessageAnalysis.entities),
                selectinload(TelegramMessage.analysis).selectinload(MessageAnalysis.routes),
                selectinload(TelegramMessage.analysis_job),
            )
            .where(TelegramMessage.id == message_id)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        limit: int,
        cursor_sent_at: datetime | None,
        cursor_id: int | None,
        query: str | None,
        chat_id: int | None,
        sender_id: int | None,
        date_from: datetime | None,
        date_to: datetime | None,
        message_type: str | None = None,
        entity_query: str | None = None,
        analysis_status: str | None = None,
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
        if cursor_sent_at is not None and cursor_id is not None:
            filters.append(
                (TelegramMessage.published_at < cursor_sent_at)
                | (
                    (TelegramMessage.published_at == cursor_sent_at)
                    & (TelegramMessage.id < cursor_id)
                )
            )
        if message_type:
            filters.append(
                TelegramMessage.analysis.has(MessageAnalysis.message_type == message_type)
            )
        if analysis_status:
            filters.append(
                TelegramMessage.analysis_job.has(MessageAnalysisJob.status == analysis_status)
            )
        if entity_query:
            filters.append(
                TelegramMessage.analysis.has(
                    MessageAnalysis.entities.any(
                        ExtractedEntity.normalized_value.ilike(f"%{entity_query}%")
                    )
                )
            )
        where_clause = and_(*filters) if filters else True
        result = await self._session.execute(
            select(TelegramMessage)
            .options(
                selectinload(TelegramMessage.chat),
                selectinload(TelegramMessage.sender),
                selectinload(TelegramMessage.analysis),
                selectinload(TelegramMessage.analysis_job),
            )
            .where(where_clause)
            .order_by(TelegramMessage.published_at.desc())
            .limit(limit + 1)
        )
        items = list(result.scalars())
        return items[:limit], len(items) > limit
