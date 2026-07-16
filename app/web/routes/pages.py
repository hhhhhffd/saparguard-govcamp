from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database.models import (
    MessageAnalysis,
    MessageAnalysisJob,
    MessageRoute,
    MediaProcessingJob,
    PlateDetection,
    ProfileIdentifier,
    ProfileOccurrence,
    ProfileRelation,
    ProfileRelationObservation,
    ProfileResolutionConflict,
    ProfileResolutionJob,
    ProfileVehicleLink,
    MessageAnnotation,
    TelegramChat,
    TelegramMessage,
    TransportProfile,
    Vehicle,
    VehicleObservation,
)
from app.review.service import (
    VALID_MESSAGE_TYPES,
    annotation_is_stale,
    ReviewFilters,
    get_review_message,
    select_review_queue,
)
from app.analytics.profile_scores import rank_profile_ids, scores_for_profiles
from app.database.repositories import MessageRepository, SourceRepository
from app.database.session import get_session
from app.web.templating import templates

router = APIRouter()
DEFAULT_PAGE_SIZE = 50


def parse_optional_identifier(value: str | None, field_name: str) -> int | None:
    """Convert optional form IDs while treating empty inputs as absent filters."""
    normalized_value = value.strip() if value else ""
    if not normalized_value:
        return None
    try:
        return int(normalized_value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"{field_name} must be a number") from error


def parse_optional_number(value: str | None, field_name: str) -> float | None:
    """Convert optional decimal form values while treating empty inputs as absent filters."""
    normalized_value = value.strip() if value else ""
    if not normalized_value:
        return None
    try:
        return float(normalized_value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"{field_name} must be a number") from error


def parse_optional_datetime(value: str | None, field_name: str) -> datetime | None:
    """Convert optional ISO date form values while treating empty inputs as absent filters."""
    normalized_value = value.strip() if value else ""
    if not normalized_value:
        return None
    try:
        return datetime.fromisoformat(normalized_value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"{field_name} must be a valid date") from error


def _review_filters_context(request: Request) -> dict[str, str]:
    return {
        key: request.query_params.get(key, "")
        for key in (
            "source_id",
            "annotation_status",
            "date_from",
            "date_to",
            "message_type",
            "confidence_min",
            "confidence_max",
            "has_phone",
            "has_route",
            "has_vehicle",
            "has_media",
            "has_plate",
            "processing_failed",
            "unannotated_only",
            "include_deleted",
            "include_empty",
            "seed",
            "annotator",
        )
    }


async def _review_sources(session: AsyncSession) -> list[TelegramChat]:
    return [source for source, _, _ in await SourceRepository(session).list()]


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
    message_id: int | None = None,
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
        message_id=message_id,
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
        "message_id": message_id or "",
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
    processed = await session.scalar(select(func.count(MessageAnalysis.id))) or 0
    total_messages = await session.scalar(select(func.count(TelegramMessage.id))) or 0
    profile_ids = list((await session.scalars(select(TransportProfile.id))).all())
    scores = await scores_for_profiles(session, profile_ids, generated_at=now)
    stats = {
        "active_sources": (
            await session.scalar(
                select(func.count(TelegramChat.id)).where(TelegramChat.is_active.is_(True))
            )
        )
        or 0,
        "total_sources": await session.scalar(select(func.count(TelegramChat.id))) or 0,
        "total_messages": total_messages,
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
    activity = []
    message_days = dict(
        (
            await session.execute(
                select(func.date(TelegramMessage.published_at), func.count())
                .where(TelegramMessage.published_at >= now - timedelta(days=7))
                .group_by(func.date(TelegramMessage.published_at))
            )
        ).all()
    )
    analysis_days = dict(
        (
            await session.execute(
                select(func.date(TelegramMessage.published_at), func.count())
                .join(MessageAnalysis)
                .where(TelegramMessage.published_at >= now - timedelta(days=7))
                .group_by(func.date(TelegramMessage.published_at))
            )
        ).all()
    )
    profile_days = dict(
        (
            await session.execute(
                select(func.date(ProfileOccurrence.first_seen_at), func.count())
                .where(ProfileOccurrence.first_seen_at >= now - timedelta(days=7))
                .group_by(func.date(ProfileOccurrence.first_seen_at))
            )
        ).all()
    )
    for day_offset in range(6, -1, -1):
        day_start = (now - timedelta(days=day_offset)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        received = message_days.get(day_start.date(), 0)
        analyzed = analysis_days.get(day_start.date(), 0)
        updated = profile_days.get(day_start.date(), 0)
        activity.append(
            {"date": day_start, "received": received, "processed": analyzed, "profiles": updated}
        )
    top_profiles = list(
        (
            await session.scalars(
                select(TransportProfile).where(TransportProfile.id.in_(profile_ids))
            )
        ).all()
    )
    top_profiles.sort(key=lambda profile: (-scores[profile.id]["score"], -profile.id))
    distribution = (
        await session.execute(
            select(MessageAnalysis.message_type, func.count())
            .group_by(MessageAnalysis.message_type)
            .order_by(func.count().desc())
        )
    ).all()
    routes = (
        await session.execute(
            select(
                MessageRoute.normalized_origin,
                MessageRoute.normalized_destination,
                func.count(func.distinct(MessageRoute.analysis_id)),
                func.count(func.distinct(ProfileOccurrence.profile_id)),
            )
            .join(MessageAnalysis)
            .join(TelegramMessage)
            .outerjoin(ProfileOccurrence, ProfileOccurrence.message_id == TelegramMessage.id)
            .where(TelegramMessage.published_at >= now - timedelta(days=7))
            .group_by(MessageRoute.normalized_origin, MessageRoute.normalized_destination)
            .order_by(func.count(func.distinct(MessageRoute.analysis_id)).desc())
            .limit(8)
        )
    ).all()
    recent_vehicles = (
        await session.execute(
            select(Vehicle, VehicleObservation)
            .join(VehicleObservation)
            .order_by(VehicleObservation.observed_at.desc())
            .limit(8)
        )
    ).all()
    jobs = {
        "text_pending": await session.scalar(
            select(func.count(MessageAnalysisJob.id)).where(MessageAnalysisJob.status == "pending")
        )
        or 0,
        "text_failed": await session.scalar(
            select(func.count(MessageAnalysisJob.id)).where(MessageAnalysisJob.status == "failed")
        )
        or 0,
        "media_pending": await session.scalar(
            select(func.count(MediaProcessingJob.id)).where(MediaProcessingJob.status == "pending")
        )
        or 0,
        "media_failed": await session.scalar(
            select(func.count(MediaProcessingJob.id)).where(MediaProcessingJob.status == "failed")
        )
        or 0,
        "resolver_pending": await session.scalar(
            select(func.count(ProfileResolutionJob.id)).where(
                ProfileResolutionJob.status == "pending"
            )
        )
        or 0,
        "resolver_failed": await session.scalar(
            select(func.count(ProfileResolutionJob.id)).where(
                ProfileResolutionJob.status == "failed"
            )
        )
        or 0,
    }
    return templates.TemplateResponse(
        request,
        "pages/dashboard.html",
        {
            "stats": stats,
            "processed_share": round(processed / total_messages * 100) if total_messages else 0,
            "profile_count": len(profile_ids),
            "vehicle_count": await session.scalar(select(func.count(Vehicle.id))) or 0,
            "plate_count": await session.scalar(select(func.count(PlateDetection.id))) or 0,
            "high_score_count": sum(item["score"] >= 50 for item in scores.values()),
            "conflict_count": await session.scalar(
                select(func.count(ProfileResolutionConflict.id)).where(
                    ProfileResolutionConflict.status == "open"
                )
            )
            or 0,
            "scores": scores,
            "activity": activity,
            "distribution": distribution,
            "routes": routes,
            "top_profiles": top_profiles[:10],
            "recent_vehicles": recent_vehicles,
            "jobs": jobs,
            "display_timezone": settings.display_timezone,
        },
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
    chat_id: str | None = None,
    sender_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    message_type: str | None = None,
    entity_query: str | None = None,
    analysis_status: str | None = None,
    message_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    context = await message_page_context(
        limit=min(max(limit, 1), 100),
        cursor_sent_at=cursor_sent_at,
        cursor_id=cursor_id,
        query=query,
        chat_id=parse_optional_identifier(chat_id, "chat_id"),
        sender_id=parse_optional_identifier(sender_id, "sender_id"),
        date_from=date_from,
        date_to=date_to,
        message_type=message_type,
        entity_query=entity_query,
        analysis_status=analysis_status,
        message_id=message_id,
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
    query: str | None = None,
    score_min: str | None = None,
    score_max: str | None = None,
    score_level: str | None = None,
    page: int = 1,
    limit: int = 50,
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
    if query:
        filters.append(TransportProfile.canonical_label.ilike(f"%{query}%"))
    if has_conflicts:
        filters.append(
            TransportProfile.id.in_(
                select(ProfileOccurrence.profile_id)
                .join(
                    ProfileResolutionConflict,
                    ProfileResolutionConflict.message_id == ProfileOccurrence.message_id,
                )
                .where(ProfileResolutionConflict.status == "open")
            )
        )
    candidate_ids = list(
        (
            await session.scalars(
                select(TransportProfile.id).where(*filters).order_by(TransportProfile.id)
            )
        ).all()
    )
    ranked_ids, scores = await rank_profile_ids(
        session,
        candidate_ids,
        generated_at=datetime.now(timezone.utc),
        score_min=parse_optional_identifier(score_min, "score_min"),
        score_max=parse_optional_identifier(score_max, "score_max"),
        score_level=score_level,
    )
    page = max(page, 1)
    limit = min(max(limit, 1), 100)
    start = (page - 1) * limit
    page_ids = ranked_ids[start : start + limit]
    profiles_by_id = {
        profile.id: profile
        for profile in (
            await session.scalars(select(TransportProfile).where(TransportProfile.id.in_(page_ids)))
        ).all()
    }
    profiles = [profiles_by_id[profile_id] for profile_id in page_ids]
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
            "scores": scores,
            "pagination": {
                "page": page,
                "has_more": start + limit < len(ranked_ids),
                "total": len(ranked_ids),
            },
            "identifiers": by_profile,
            "filters": {
                "phone": phone or "",
                "telegram_user_id": telegram_user_id or "",
                "plate": plate or "",
                "vehicle": vehicle or "",
                "has_conflicts": has_conflicts,
                "query": query or "",
                "score_min": score_min or "",
                "score_max": score_max or "",
                "score_level": score_level or "",
            },
            "display_timezone": settings.display_timezone,
        },
    )


@router.get("/profiles/{profile_id}", response_class=HTMLResponse)
async def profile_page(
    profile_id: int,
    request: Request,
    timeline_page: int = 1,
    session: AsyncSession = Depends(get_session),
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
    timeline_page = max(timeline_page, 1)
    timeline_limit = 50
    occurrence_total = (
        await session.scalar(
            select(func.count(ProfileOccurrence.id)).where(
                ProfileOccurrence.profile_id == profile_id
            )
        )
        or 0
    )
    occurrences = (
        await session.execute(
            select(ProfileOccurrence, TelegramMessage)
            .join(TelegramMessage)
            .where(ProfileOccurrence.profile_id == profile_id)
            .order_by(TelegramMessage.published_at.desc())
            .offset((timeline_page - 1) * timeline_limit)
            .limit(timeline_limit)
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
    scores = await scores_for_profiles(
        session, [profile_id], generated_at=datetime.now(timezone.utc)
    )
    relation_items = list(
        (
            await session.scalars(
                select(ProfileRelation).where(
                    or_(
                        ProfileRelation.left_profile_id == profile_id,
                        ProfileRelation.right_profile_id == profile_id,
                    )
                )
            )
        ).all()
    )
    related_ids = {
        relation.right_profile_id
        if relation.left_profile_id == profile_id
        else relation.left_profile_id
        for relation in relation_items
    }
    related_profiles = {
        item.id: item
        for item in (
            await session.scalars(
                select(TransportProfile).where(TransportProfile.id.in_(related_ids))
            )
        ).all()
    }
    relations = []
    for relation in relation_items:
        related_id = (
            relation.right_profile_id
            if relation.left_profile_id == profile_id
            else relation.left_profile_id
        )
        related_profile = related_profiles.get(related_id)
        if related_profile is None:
            continue
        evidence_message_id = await session.scalar(
            select(ProfileRelationObservation.message_id)
            .where(
                ProfileRelationObservation.left_profile_id == relation.left_profile_id,
                ProfileRelationObservation.right_profile_id == relation.right_profile_id,
                ProfileRelationObservation.relation_type == relation.relation_type,
            )
            .order_by(ProfileRelationObservation.observed_at.desc())
            .limit(1)
        )
        relations.append(
            {
                "type": relation.relation_type,
                "profile": related_profile,
                "confidence": relation.confidence,
                "occurrence_count": relation.occurrence_count,
                "first_seen_at": relation.first_seen_at,
                "last_seen_at": relation.last_seen_at,
                "evidence_message_id": evidence_message_id,
            }
        )
    conflicts = list(
        (
            await session.scalars(
                select(ProfileResolutionConflict).where(
                    ProfileResolutionConflict.message_id.in_(
                        select(ProfileOccurrence.message_id).where(
                            ProfileOccurrence.profile_id == profile_id
                        )
                    )
                )
            )
        ).all()
    )
    return templates.TemplateResponse(
        request,
        "pages/profile_detail.html",
        {
            "profile": profile,
            "identifiers": identifiers,
            "occurrences": occurrences,
            "vehicles": vehicles,
            "priority": scores[profile_id],
            "relations": relations,
            "timeline": {
                "page": timeline_page,
                "has_more": timeline_page * timeline_limit < occurrence_total,
                "total": occurrence_total,
            },
            "conflicts": conflicts,
            "display_timezone": settings.display_timezone,
        },
    )


@router.get("/vehicles", response_class=HTMLResponse)
async def vehicles_page(
    request: Request,
    query: str | None = None,
    page: int = 1,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    statement = select(Vehicle)
    if query:
        statement = statement.where(
            or_(
                Vehicle.normalized_plate.ilike(f"%{query}%"),
                Vehicle.canonical_label.ilike(f"%{query}%"),
                Vehicle.make.ilike(f"%{query}%"),
                Vehicle.model.ilike(f"%{query}%"),
            )
        )
    page = max(page, 1)
    limit = 50
    total = await session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    vehicles = list(
        (
            await session.scalars(
                statement.order_by(Vehicle.last_seen_at.desc())
                .offset((page - 1) * limit)
                .limit(limit)
            )
        ).all()
    )
    profile_counts = (
        dict(
            (
                await session.execute(
                    select(ProfileVehicleLink.vehicle_id, func.count())
                    .where(ProfileVehicleLink.vehicle_id.in_([vehicle.id for vehicle in vehicles]))
                    .group_by(ProfileVehicleLink.vehicle_id)
                )
            ).all()
        )
        if vehicles
        else {}
    )
    return templates.TemplateResponse(
        request,
        "pages/vehicles.html",
        {
            "vehicles": vehicles,
            "profile_counts": profile_counts,
            "query": query or "",
            "pagination": {"page": page, "has_more": page * limit < total, "total": total},
            "display_timezone": settings.display_timezone,
        },
    )


@router.get("/vehicles/{vehicle_id}", response_class=HTMLResponse)
async def vehicle_page(
    vehicle_id: int,
    request: Request,
    timeline_page: int = 1,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    vehicle = await session.get(Vehicle, vehicle_id)
    if vehicle is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Vehicle not found")
    timeline_page = max(timeline_page, 1)
    timeline_limit = 50
    observation_total = (
        await session.scalar(
            select(func.count(VehicleObservation.id)).where(
                VehicleObservation.vehicle_id == vehicle_id
            )
        )
        or 0
    )
    observations = (
        await session.execute(
            select(VehicleObservation, TelegramMessage)
            .join(TelegramMessage)
            .where(VehicleObservation.vehicle_id == vehicle_id)
            .order_by(VehicleObservation.observed_at.desc())
            .offset((timeline_page - 1) * timeline_limit)
            .limit(timeline_limit)
        )
    ).all()
    profiles = (
        await session.execute(
            select(TransportProfile, ProfileVehicleLink)
            .join(ProfileVehicleLink)
            .where(ProfileVehicleLink.vehicle_id == vehicle_id)
        )
    ).all()
    return templates.TemplateResponse(
        request,
        "pages/vehicle_detail.html",
        {
            "vehicle": vehicle,
            "observations": observations,
            "profiles": profiles,
            "timeline": {
                "page": timeline_page,
                "has_more": timeline_page * timeline_limit < observation_total,
                "total": observation_total,
            },
            "display_timezone": settings.display_timezone,
        },
    )


@router.get("/graph", response_class=HTMLResponse)
async def graph_page(
    request: Request, session: AsyncSession = Depends(get_session)
) -> HTMLResponse:
    profiles = list(
        (
            await session.scalars(
                select(TransportProfile).order_by(TransportProfile.last_seen_at.desc()).limit(50)
            )
        ).all()
    )
    relationship_count = await session.scalar(select(func.count(ProfileRelation.id))) or 0
    return templates.TemplateResponse(
        request,
        "pages/graph.html",
        {
            "profiles": profiles,
            "relationship_count": relationship_count,
            "display_timezone": settings.display_timezone,
        },
    )


@router.get("/quality", response_class=HTMLResponse)
async def quality_page(
    request: Request, session: AsyncSession = Depends(get_session)
) -> HTMLResponse:
    from app.evaluation.report import load_latest_report

    total = await session.scalar(select(func.count(TelegramMessage.id))) or 0
    review_rows = (
        await session.execute(
            select(MessageAnnotation, TelegramMessage.text)
            .join(TelegramMessage)
            .where(MessageAnnotation.status == "reviewed")
        )
    ).all()
    reviewed = sum(not annotation_is_stale(annotation, text) for annotation, text in review_rows)
    stale = len(review_rows) - reviewed
    skipped = (
        await session.scalar(
            select(func.count(MessageAnnotation.id)).where(MessageAnnotation.status == "skipped")
        )
        or 0
    )
    draft = (
        await session.scalar(
            select(func.count(MessageAnnotation.id)).where(MessageAnnotation.status == "draft")
        )
        or 0
    )
    annotated = reviewed + stale + skipped + draft
    human_report = load_latest_report(Path("evaluation/local-reviewed/reports"))
    return templates.TemplateResponse(
        request,
        "pages/quality.html",
        {
            "synthetic_report": load_latest_report(),
            "human_report": human_report,
            "coverage": {
                "total": total,
                "text_processed": await session.scalar(select(func.count(MessageAnalysis.id))) or 0,
                "text_pending": await session.scalar(
                    select(func.count(MessageAnalysisJob.id)).where(
                        MessageAnalysisJob.status == "pending"
                    )
                )
                or 0,
                "text_failed": await session.scalar(
                    select(func.count(MessageAnalysisJob.id)).where(
                        MessageAnalysisJob.status == "failed"
                    )
                )
                or 0,
                "media_processed": await session.scalar(
                    select(func.count(func.distinct(MediaProcessingJob.message_id))).where(
                        MediaProcessingJob.status == "completed"
                    )
                )
                or 0,
                "media_pending": await session.scalar(
                    select(func.count(func.distinct(MediaProcessingJob.message_id))).where(
                        MediaProcessingJob.status == "pending"
                    )
                )
                or 0,
                "media_failed": await session.scalar(
                    select(func.count(func.distinct(MediaProcessingJob.message_id))).where(
                        MediaProcessingJob.status == "failed"
                    )
                )
                or 0,
                "resolver_processed": await session.scalar(
                    select(func.count(func.distinct(ProfileResolutionJob.message_id))).where(
                        ProfileResolutionJob.status == "completed"
                    )
                )
                or 0,
                "resolver_pending": (
                    await session.scalar(
                        select(func.count(ProfileResolutionJob.id)).where(
                            ProfileResolutionJob.status == "pending"
                        )
                    )
                    or 0
                ),
                "resolver_failed": (
                    await session.scalar(
                        select(func.count(ProfileResolutionJob.id)).where(
                            ProfileResolutionJob.status == "failed"
                        )
                    )
                    or 0
                ),
                "unreviewed": max(total - annotated, 0),
                "draft": draft,
                "reviewed": reviewed,
                "stale": stale,
                "skipped": skipped,
                "reviewed_share": reviewed / total if total else None,
            },
            "display_timezone": settings.display_timezone,
        },
    )


@router.get("/review", response_class=HTMLResponse)
async def review_page(
    request: Request,
    ids: str | None = None,
    index: int = 0,
    limit: int = 50,
    seed: int = 0,
    source_id: str | None = None,
    annotation_status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    message_type: str | None = None,
    confidence_min: str | None = None,
    confidence_max: str | None = None,
    has_phone: bool | None = None,
    has_route: bool | None = None,
    has_vehicle: bool | None = None,
    has_media: bool | None = None,
    has_plate: bool | None = None,
    processing_failed: bool = False,
    unannotated_only: bool = False,
    include_deleted: bool = False,
    include_empty: bool = False,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    if message_type and message_type not in VALID_MESSAGE_TYPES:
        raise HTTPException(status_code=422, detail="Недопустимый тип сообщения")
    filter_query = urlencode(
        {key: value for key, value in request.query_params.items() if key not in {"ids", "index"}}
    )
    queue = [int(value) for value in ids.split(",") if value.isdigit()][:200] if ids else []
    if not queue:
        queue = await select_review_queue(
            session,
            ReviewFilters(
                source_id=parse_optional_identifier(source_id, "source_id"),
                annotation_status=annotation_status,
                date_from=parse_optional_datetime(date_from, "date_from"),
                date_to=parse_optional_datetime(date_to, "date_to"),
                message_type=message_type,
                confidence_min=parse_optional_number(confidence_min, "confidence_min"),
                confidence_max=parse_optional_number(confidence_max, "confidence_max"),
                has_phone=has_phone,
                has_route=has_route,
                has_vehicle=has_vehicle,
                has_media=has_media,
                has_plate=has_plate,
                processing_failed=processing_failed,
                unannotated_only=unannotated_only,
                include_deleted=include_deleted,
                include_empty=include_empty,
            ),
            limit=min(max(limit, 1), 200),
            seed=seed,
        )
    if not queue:
        return templates.TemplateResponse(
            request,
            "pages/review.html",
            {
                "message": None,
                "queue": [],
                "index": 0,
                "review_filters": _review_filters_context(request),
                "review_sources": await _review_sources(session),
                "message_types": sorted(VALID_MESSAGE_TYPES),
                "display_timezone": settings.display_timezone,
            },
        )
    index = min(max(index, 0), len(queue) - 1)
    return await review_message_page(
        request,
        queue[index],
        ",".join(map(str, queue)),
        index,
        session,
        filter_query,
    )


@router.get("/review/{message_id}", response_class=HTMLResponse)
async def review_message_page(
    request: Request,
    message_id: int,
    ids: str | None = None,
    index: int = 0,
    session: AsyncSession = Depends(get_session),
    filter_query: str | None = None,
) -> HTMLResponse:
    message = await get_review_message(session, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    queue = (
        [int(value) for value in ids.split(",") if value.isdigit()][:200] if ids else [message_id]
    )
    if message_id not in queue:
        queue.insert(0, message_id)
    index = queue.index(message_id) if message_id in queue else index
    filter_query = filter_query or urlencode(
        {key: value for key, value in request.query_params.items() if key not in {"ids", "index"}}
    )
    return templates.TemplateResponse(
        request,
        "pages/review.html",
        {
            "message": message,
            "queue": queue,
            "queue_ids": ",".join(map(str, queue)),
            "filter_query": filter_query,
            "index": index,
            "review_filters": _review_filters_context(request),
            "review_sources": await _review_sources(session),
            "message_types": sorted(VALID_MESSAGE_TYPES),
            "annotation_stale": bool(
                message.annotation and annotation_is_stale(message.annotation, message.text)
            ),
            "display_timezone": settings.display_timezone,
        },
    )


@router.get("/conflicts", response_class=HTMLResponse)
async def conflicts_page(
    request: Request,
    status: str = "open",
    page: int = 1,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    if status not in {"open", "reviewed", "dismissed"}:
        raise HTTPException(status_code=422, detail="Unsupported conflict status")
    page = max(page, 1)
    limit = 50
    statement = (
        select(ProfileResolutionConflict)
        .where(ProfileResolutionConflict.status == status)
        .order_by(ProfileResolutionConflict.created_at.desc())
    )
    total = await session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    conflicts = list(
        (await session.scalars(statement.offset((page - 1) * limit).limit(limit))).all()
    )
    return templates.TemplateResponse(
        request,
        "pages/conflicts.html",
        {
            "conflicts": conflicts,
            "status": status,
            "pagination": {"page": page, "has_more": page * limit < total, "total": total},
            "display_timezone": settings.display_timezone,
        },
    )
