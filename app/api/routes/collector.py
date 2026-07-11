from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CollectorState, TelegramChat
from app.database.session import get_session

router = APIRouter(prefix="/collector", tags=["collector"])


@router.get("/status")
async def collector_status(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    states = list((await session.scalars(select(CollectorState).order_by(desc(CollectorState.last_synced_at)).limit(20))))
    errors = list(
        (
            await session.execute(
                select(TelegramChat.title, TelegramChat.username, TelegramChat.last_error)
                .where(TelegramChat.last_error.is_not(None))
                .order_by(desc(TelegramChat.updated_at))
                .limit(20)
            )
        ).all()
    )
    return {
        "sources_with_state": len(states),
        "states": [
            {
                "telegram_chat_id": item.telegram_chat_id,
                "last_message_id": item.last_message_id,
                "last_synced_at": item.last_synced_at,
                "last_sync_status": item.last_sync_status,
                "last_error": item.last_error,
            }
            for item in states
        ],
        "errors": [
            {"title": row.title, "username": row.username, "error": row.last_error} for row in errors
        ],
    }
