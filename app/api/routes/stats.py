from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import TelegramChat, TelegramMessage
from app.database.session import get_session

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("")
async def get_stats(
    session: AsyncSession = Depends(get_session),
) -> dict[str, int | datetime | None]:
    now = datetime.now(timezone.utc)
    return {
        "active_sources": (
            await session.scalar(
                select(func.count(TelegramChat.id)).where(TelegramChat.is_active.is_(True))
            )
        )
        or 0,
        "total_sources": (await session.scalar(select(func.count(TelegramChat.id)))) or 0,
        "total_messages": (await session.scalar(select(func.count(TelegramMessage.id)))) or 0,
        "messages_last_24_hours": (
            await session.scalar(
                select(func.count(TelegramMessage.id)).where(
                    TelegramMessage.published_at >= now - timedelta(days=1)
                )
            )
        )
        or 0,
        "last_message_at": await session.scalar(select(func.max(TelegramMessage.published_at))),
    }
