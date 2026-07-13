from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import TelegramMessage
from app.database.repositories import MessageRepository
from app.database.session import get_session
from app.schemas.messages import (
    ChatShortRead,
    AnalysisSummaryRead,
    ExtractedEntityRead,
    MessageCursor,
    MessageDetailRead,
    MessageEditRead,
    MediaFileRead,
    MessagePage,
    PlateDetectionRead,
    MessageRead,
    RouteRead,
    SenderRead,
)

router = APIRouter(prefix="/messages", tags=["messages"])


def analysis_is_current(message: TelegramMessage) -> bool:
    return bool(
        message.analysis
        and message.analysis_job
        and message.analysis_job.status == "completed"
        and message.analysis.source_text_hash == message.analysis_job.source_text_hash
        and message.analysis.analyzer_version == message.analysis_job.analyzer_version
    )


def serialize_message(
    message: TelegramMessage, include_details: bool = False
) -> MessageRead | MessageDetailRead:
    current_analysis = analysis_is_current(message)
    analysis_status = (
        "reprocessing"
        if message.analysis and not current_analysis
        else (message.analysis_job.status if message.analysis_job else None)
    )
    data: dict[str, Any] = {
        "id": message.id,
        "telegram_message_id": message.telegram_message_id,
        "text": message.text,
        "published_at": message.published_at,
        "saved_at": message.saved_at,
        "is_forwarded": message.is_forwarded,
        "forward_source_id": message.forward_source_id,
        "forward_source_name": message.forward_source_name,
        "media_type": message.media_type,
        "edited_at": message.edited_at,
        "is_deleted": message.is_deleted,
        "deleted_at": message.deleted_at,
        "chat": ChatShortRead(
            telegram_chat_id=message.chat.telegram_chat_id,
            title=message.chat.title,
            username=message.chat.username,
            chat_type=message.chat.chat_type,
        ),
        "sender": (
            SenderRead(
                telegram_user_id=message.sender.telegram_user_id,
                first_name=message.sender.first_name,
                last_name=message.sender.last_name,
                username=message.sender.username,
            )
            if message.sender
            else None
        ),
        "analysis": AnalysisSummaryRead(
            status=analysis_status,
            message_type=message.analysis.message_type if current_analysis else None,
            classification_confidence=message.analysis.classification_confidence
            if current_analysis
            else None,
        ),
    }
    if include_details:
        analysis = message.analysis if current_analysis else None
        entities = analysis.entities if analysis else []
        data["edits"] = [
            MessageEditRead(
                id=edit.id,
                previous_text=edit.previous_text,
                detected_at=edit.detected_at,
            )
            for edit in message.edits
        ]
        data["media_files"] = [
            MediaFileRead(
                id=media.id,
                mime_type=media.mime_type,
                processing_status=media.processing_status,
                last_error=media.jobs[0].last_error if media.jobs else None,
                plates=[
                    PlateDetectionRead(
                        raw_text=plate.raw_text,
                        normalized_text=plate.normalized_text,
                        confidence=plate.confidence,
                    )
                    for plate in media.plate_detections
                ],
            )
            for media in message.media_files
        ]
        data["analysis_status"] = analysis_status
        data["analyzer_version"] = (
            analysis.analyzer_version
            if analysis
            else (message.analysis_job.analyzer_version if message.analysis_job else None)
        )
        data["analysis_error"] = message.analysis_job.last_error if message.analysis_job else None
        data["attributes"] = analysis.attributes if analysis else {}
        data["classification_evidence"] = analysis.classification_evidence if analysis else []
        data["phones"] = [
            ExtractedEntityRead(
                entity_type=e.entity_type,
                role=e.role,
                raw_value=e.raw_value,
                normalized_value=e.normalized_value,
                confidence=e.confidence,
                evidence=e.evidence,
                metadata=e.metadata_,
            )
            for e in entities
            if e.entity_type == "phone"
        ]
        data["vehicles"] = [
            ExtractedEntityRead(
                entity_type=e.entity_type,
                role=e.role,
                raw_value=e.raw_value,
                normalized_value=e.normalized_value,
                confidence=e.confidence,
                evidence=e.evidence,
                metadata=e.metadata_,
            )
            for e in entities
            if e.entity_type == "vehicle"
        ]
        data["locations"] = [
            ExtractedEntityRead(
                entity_type=e.entity_type,
                role=e.role,
                raw_value=e.raw_value,
                normalized_value=e.normalized_value,
                confidence=e.confidence,
                evidence=e.evidence,
                metadata=e.metadata_,
            )
            for e in entities
            if e.entity_type == "location"
        ]
        data["routes"] = [
            RouteRead(
                raw_origin=r.raw_origin,
                normalized_origin=r.normalized_origin,
                raw_destination=r.raw_destination,
                normalized_destination=r.normalized_destination,
                confidence=r.confidence,
                evidence=r.evidence,
            )
            for r in (analysis.routes if analysis else [])
        ]
        return MessageDetailRead(**data)
    return MessageRead(**data)


@router.get("", response_model=MessagePage)
async def list_messages(
    limit: int = Query(default=50, ge=1, le=100),
    cursor_sent_at: datetime | None = None,
    cursor_id: int | None = None,
    query: str | None = None,
    chat_id: int | None = None,
    sender_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    message_type: str | None = None,
    entity_query: str | None = None,
    analysis_status: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> MessagePage:
    if (cursor_sent_at is None) != (cursor_id is None):
        raise HTTPException(
            status_code=422, detail="cursor_sent_at and cursor_id must be supplied together"
        )
    messages, has_more = await MessageRepository(session).list(
        limit=limit,
        cursor_sent_at=cursor_sent_at,
        cursor_id=cursor_id,
        query=query,
        chat_id=chat_id,
        sender_id=sender_id,
        date_from=date_from,
        date_to=date_to,
        message_type=message_type,
        entity_query=entity_query,
        analysis_status=analysis_status,
    )
    next_cursor = (
        MessageCursor(sent_at=messages[-1].published_at, id=messages[-1].id)
        if messages and has_more
        else None
    )
    return MessagePage(
        items=[serialize_message(item) for item in messages],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get("/{message_id}", response_model=MessageDetailRead)
async def get_message(
    message_id: int, session: AsyncSession = Depends(get_session)
) -> MessageDetailRead:
    message = await MessageRepository(session).get(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return serialize_message(message, include_details=True)
