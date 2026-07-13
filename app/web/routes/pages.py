from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database.models import (
    ProfileIdentifier,
    ProfileOccurrence,
    ProfileVehicleLink,
    TelegramChat,
    TelegramMessage,
    TransportProfile,
    Vehicle,
)
from app.database.repositories import MessageRepository, SourceRepository
from app.database.session import get_session
from app.web.templating import templates

router = APIRouter()
DEFAULT_PAGE_SIZE = 50


async def message_page_context(
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
    session: AsyncSession,
) -> dict[str, object]:
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
        {"cursor_sent_at": messages[-1].published_at.isoformat(), "cursor_id": messages[-1].id}
        if messages and has_more
        else None
    )
    filters = {
        "limit": limit,
        "query": query or "",
        "chat_id": chat_id or "",
        "sender_id": sender_id or "",
        "date_from": date_from.isoformat() if date_from else "",
        "date_to": date_to.isoformat() if date_to else "",
        "message_type": message_type or "",
        "entity_query": entity_query or "",
        "analysis_status": analysis_status or "",
    }
    pagination_values = {key: value for key, value in filters.items() if value != ""}
    if next_cursor:
        pagination_values.update(next_cursor)
    page_values = {key: value for key, value in filters.items() if value != ""}
    if cursor_sent_at is not None and cursor_id is not None:
        page_values.update({"cursor_sent_at": cursor_sent_at.isoformat(), "cursor_id": cursor_id})
    return {
        "messages": messages,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "filters": filters,
        "next_page_query": urlencode(pagination_values),
        "page_url": f"/messages?{urlencode(page_values)}" if page_values else "/messages",
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    now = datetime.now(timezone.utc)
    stats = {
        "active_sources": (
            await session.scalar(
                select(func.count(TelegramChat.id)).where(TelegramChat.is_active.is_(True))
            )
        )
        or 0,
        "total_sources": await session.scalar(select(func.count(TelegramChat.id))) or 0,
        "total_messages": await session.scalar(select(func.count(TelegramMessage.id))) or 0,
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
    return templates.TemplateResponse(
        request,
        "pages/dashboard.html",
        {"stats": stats, "display_timezone": settings.display_timezone},
    )


@router.get("/sources", response_class=HTMLResponse)
async def sources_page(
    request: Request, session: AsyncSession = Depends(get_session)
) -> HTMLResponse:
    sources = await SourceRepository(session).list()
    return templates.TemplateResponse(
        request,
        "pages/sources.html",
        {"sources": sources, "display_timezone": settings.display_timezone},
    )


@router.get("/messages", response_class=HTMLResponse)
async def messages_page(
    request: Request,
    limit: int = DEFAULT_PAGE_SIZE,
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
) -> HTMLResponse:
    context = await message_page_context(
        limit=min(max(limit, 1), 100),
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
        session=session,
    )
    context["display_timezone"] = settings.display_timezone
    return templates.TemplateResponse(request, "pages/messages.html", context)


@router.get("/profiles", response_class=HTMLResponse)
async def profiles_page(
    request: Request,
    phone: str | None = None,
    telegram_user_id: str | None = None,
    plate: str | None = None,
    vehicle: str | None = None,
    has_conflicts: bool | None = None,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    filters = []
    if phone:
        filters.append(
            TransportProfile.id.in_(
                select(ProfileIdentifier.profile_id).where(
                    ProfileIdentifier.identifier_type == "phone",
                    ProfileIdentifier.normalized_value.ilike(f"%{phone}%"),
                )
            )
        )
    if telegram_user_id:
        filters.append(
            TransportProfile.id.in_(
                select(ProfileIdentifier.profile_id).where(
                    ProfileIdentifier.identifier_type == "telegram_user_id",
                    ProfileIdentifier.normalized_value.ilike(f"%{telegram_user_id}%"),
                )
            )
        )
    if plate or vehicle:
        vehicle_query = select(ProfileVehicleLink.profile_id).join(Vehicle)
        if plate:
            vehicle_query = vehicle_query.where(Vehicle.normalized_plate.ilike(f"%{plate}%"))
        if vehicle:
            vehicle_query = vehicle_query.where(Vehicle.canonical_label.ilike(f"%{vehicle}%"))
        filters.append(TransportProfile.id.in_(vehicle_query))
    profiles = list(
        (
            await session.scalars(
                select(TransportProfile)
                .where(*filters)
                .order_by(TransportProfile.last_seen_at.desc())
                .limit(100)
            )
        ).all()
    )
    identifiers = (
        (
            await session.execute(
                select(
                    ProfileIdentifier.profile_id,
                    ProfileIdentifier.identifier_type,
                    ProfileIdentifier.normalized_value,
                ).where(ProfileIdentifier.profile_id.in_([profile.id for profile in profiles]))
            )
        ).all()
        if profiles
        else []
    )
    by_profile: dict[int, list[tuple[str, str]]] = {profile.id: [] for profile in profiles}
    for profile_id, identifier_type, value in identifiers:
        by_profile[profile_id].append((identifier_type, value))
    return templates.TemplateResponse(
        request,
        "pages/profiles.html",
        {
            "profiles": profiles,
            "identifiers": by_profile,
            "filters": {
                "phone": phone or "",
                "telegram_user_id": telegram_user_id or "",
                "plate": plate or "",
                "vehicle": vehicle or "",
                "has_conflicts": has_conflicts,
            },
            "display_timezone": settings.display_timezone,
        },
    )


@router.get("/profiles/{profile_id}", response_class=HTMLResponse)
async def profile_page(
    profile_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> HTMLResponse:
    profile = await session.get(TransportProfile, profile_id)
    if profile is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Profile not found")
    identifiers = list(
        (
            await session.scalars(
                select(ProfileIdentifier).where(ProfileIdentifier.profile_id == profile_id)
            )
        ).all()
    )
    occurrences = (
        await session.execute(
            select(ProfileOccurrence, TelegramMessage)
            .join(TelegramMessage)
            .where(ProfileOccurrence.profile_id == profile_id)
            .order_by(TelegramMessage.published_at.desc())
            .limit(100)
        )
    ).all()
    vehicles = (
        (
            await session.execute(
                select(Vehicle)
                .join(ProfileVehicleLink)
                .where(ProfileVehicleLink.profile_id == profile_id)
            )
        )
        .scalars()
        .all()
    )
    return templates.TemplateResponse(
        request,
        "pages/profile_detail.html",
        {
            "profile": profile,
            "identifiers": identifiers,
            "occurrences": occurrences,
            "vehicles": vehicles,
            "display_timezone": settings.display_timezone,
        },
    )


@router.get("/vehicles/{vehicle_id}", response_class=HTMLResponse)
async def vehicle_page(
    vehicle_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> HTMLResponse:
    vehicle = await session.get(Vehicle, vehicle_id)
    if vehicle is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Vehicle not found")
    return templates.TemplateResponse(
        request,
        "pages/vehicle_detail.html",
        {"vehicle": vehicle, "display_timezone": settings.display_timezone},
    )
