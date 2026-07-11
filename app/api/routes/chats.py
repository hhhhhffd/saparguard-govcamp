from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import TelegramChat
from app.database.repositories import SourceRepository
from app.database.session import get_session
from app.schemas.chats import SourceCreate, SourceRead

router = APIRouter(prefix="/sources", tags=["sources"])


def serialize_source(
    source: TelegramChat, message_count: int = 0, last_message_at: object = None
) -> SourceRead:
    return SourceRead(
        id=source.id,
        telegram_chat_id=source.telegram_chat_id,
        username=source.username,
        title=source.title,
        chat_type=source.chat_type,
        is_active=source.is_active,
        load_history=source.load_history,
        history_limit=source.history_limit,
        collect_from_date=source.collect_from_date,
        history_requested_at=source.history_requested_at,
        last_synced_at=source.last_synced_at,
        last_error=source.last_error,
        message_count=message_count,
        last_message_at=last_message_at,
    )


@router.get("", response_model=list[SourceRead])
async def list_sources(session: AsyncSession = Depends(get_session)) -> list[SourceRead]:
    rows = await SourceRepository(session).list()
    return [
        serialize_source(source, count, last_message_at) for source, count, last_message_at in rows
    ]


@router.post("", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: SourceCreate, session: AsyncSession = Depends(get_session)
) -> SourceRead:
    async with session.begin():
        source = await SourceRepository(session).create(**payload.model_dump())
    return serialize_source(source)


@router.post("/{source_id}/enable", response_model=SourceRead)
async def enable_source(source_id: int, session: AsyncSession = Depends(get_session)) -> SourceRead:
    async with session.begin():
        source = await SourceRepository(session).set_active(source_id, True)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return serialize_source(source)


@router.post("/{source_id}/disable", response_model=SourceRead)
async def disable_source(
    source_id: int, session: AsyncSession = Depends(get_session)
) -> SourceRead:
    async with session.begin():
        source = await SourceRepository(session).set_active(source_id, False)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return serialize_source(source)


@router.post("/{source_id}/history", response_model=SourceRead)
async def request_history(
    source_id: int, session: AsyncSession = Depends(get_session)
) -> SourceRead:
    async with session.begin():
        source = await SourceRepository(session).request_history(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return serialize_source(source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: int, session: AsyncSession = Depends(get_session)) -> Response:
    async with session.begin():
        removed = await SourceRepository(session).remove(source_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Source not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
