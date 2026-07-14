from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    MessageAnalysis,
    MessageRoute,
    ProfileIdentifier,
    ProfileOccurrence,
    ProfileRelation,
    ProfileResolutionConflict,
    ProfileVehicleLink,
    TelegramMessage,
    TransportProfile,
    Vehicle,
    VehicleObservation,
)
from app.database.session import get_session
from app.analytics.profile_scores import scores_for_profiles

router = APIRouter(prefix="/profiles", tags=["profiles"])
vehicles_router = APIRouter(prefix="/vehicles", tags=["vehicles"])


def model_data(model: object, fields: tuple[str, ...]) -> dict[str, object]:
    return {field: getattr(model, field) for field in fields}


def profile_summary(
    profile: TransportProfile,
    phones: list[str],
    telegram: list[str],
    vehicles: int,
    relations: int,
    conflicts: int,
) -> dict[str, object]:
    return {
        "id": profile.id,
        "canonical_label": profile.canonical_label,
        "kind": profile.profile_kind,
        "phones": phones,
        "telegram_identifiers": telegram,
        "first_seen_at": profile.first_seen_at,
        "last_seen_at": profile.last_seen_at,
        "occurrence_count": profile.occurrence_count,
        "active_occurrence_count": profile.active_occurrence_count,
        "vehicle_count": vehicles,
        "relation_count": relations,
        "conflict_count": conflicts,
    }


@router.get("")
async def list_profiles(
    query: str | None = None,
    phone: str | None = None,
    telegram_user_id: str | None = None,
    plate: str | None = None,
    vehicle: str | None = None,
    route_origin: str | None = None,
    route_destination: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    has_conflicts: bool | None = None,
    score_min: int | None = Query(None, ge=0, le=100),
    score_max: int | None = Query(None, ge=0, le=100),
    score_level: str | None = None,
    sort: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    cursor: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    filters = []
    if cursor is not None:
        filters.append(TransportProfile.id < cursor)
    if query:
        filters.append(TransportProfile.canonical_label.ilike(f"%{query}%"))
    for value, identifier_type in ((phone, "phone"), (telegram_user_id, "telegram_user_id")):
        if value:
            filters.append(
                TransportProfile.id.in_(
                    select(ProfileIdentifier.profile_id).where(
                        ProfileIdentifier.identifier_type == identifier_type,
                        ProfileIdentifier.normalized_value.ilike(f"%{value}%"),
                    )
                )
            )
    if plate or vehicle:
        vehicle_filters = []
        if plate:
            vehicle_filters.append(Vehicle.normalized_plate.ilike(f"%{plate}%"))
        if vehicle:
            vehicle_filters.append(
                or_(
                    Vehicle.make.ilike(f"%{vehicle}%"),
                    Vehicle.model.ilike(f"%{vehicle}%"),
                    Vehicle.canonical_label.ilike(f"%{vehicle}%"),
                )
            )
        filters.append(
            TransportProfile.id.in_(
                select(ProfileVehicleLink.profile_id).join(Vehicle).where(and_(*vehicle_filters))
            )
        )
    if route_origin or route_destination or date_from or date_to:
        occurrence_filters = []
        if date_from:
            occurrence_filters.append(TelegramMessage.published_at >= date_from)
        if date_to:
            occurrence_filters.append(TelegramMessage.published_at <= date_to)
        route_filters = []
        if route_origin:
            route_filters.append(MessageRoute.normalized_origin.ilike(f"%{route_origin}%"))
        if route_destination:
            route_filters.append(
                MessageRoute.normalized_destination.ilike(f"%{route_destination}%")
            )
        messages = (
            select(ProfileOccurrence.profile_id)
            .join(TelegramMessage)
            .join(MessageAnalysis)
            .where(*occurrence_filters)
        )
        if route_filters:
            messages = messages.join(MessageRoute).where(*route_filters)
        filters.append(TransportProfile.id.in_(messages))
    conflict_count = (
        select(func.count(ProfileResolutionConflict.id))
        .join(
            ProfileOccurrence, ProfileOccurrence.message_id == ProfileResolutionConflict.message_id
        )
        .where(ProfileOccurrence.profile_id == TransportProfile.id)
        .scalar_subquery()
    )
    if has_conflicts is not None:
        filters.append(conflict_count > 0 if has_conflicts else conflict_count == 0)
    statement = (
        select(TransportProfile, conflict_count.label("conflicts"))
        .where(*filters)
        .order_by(TransportProfile.id.desc())
        .limit(limit + 1)
    )
    rows = (await session.execute(statement)).all()
    profiles = [row[0] for row in rows[:limit]]
    ids = [profile.id for profile in profiles]
    identifiers = (
        (
            await session.execute(
                select(
                    ProfileIdentifier.profile_id,
                    ProfileIdentifier.identifier_type,
                    ProfileIdentifier.normalized_value,
                ).where(ProfileIdentifier.profile_id.in_(ids))
            )
        ).all()
        if ids
        else []
    )
    vehicle_counts = (
        dict(
            (
                await session.execute(
                    select(ProfileVehicleLink.profile_id, func.count())
                    .where(ProfileVehicleLink.profile_id.in_(ids))
                    .group_by(ProfileVehicleLink.profile_id)
                )
            ).all()
        )
        if ids
        else {}
    )
    relation_counts = (
        {
            profile_id: count
            for profile_id, count in (
                await session.execute(
                    select(ProfileRelation.left_profile_id, func.count())
                    .where(ProfileRelation.left_profile_id.in_(ids))
                    .group_by(ProfileRelation.left_profile_id)
                )
            ).all()
        }
        if ids
        else {}
    )
    by_profile: dict[int, dict[str, list[str]]] = {
        profile_id: {"phone": [], "telegram_user_id": []} for profile_id in ids
    }
    for profile_id, identifier_type, value in identifiers:
        if identifier_type in by_profile[profile_id]:
            by_profile[profile_id][identifier_type].append(value)
    scores = await scores_for_profiles(session, ids, generated_at=datetime.now(timezone.utc))
    items = [
        {
            **profile_summary(
                profile,
                by_profile[profile.id]["phone"],
                by_profile[profile.id]["telegram_user_id"],
                vehicle_counts.get(profile.id, 0),
                relation_counts.get(profile.id, 0),
                conflicts,
            ),
            "priority": scores[profile.id],
        }
        for profile, conflicts in rows[:limit]
    ]
    if score_min is not None:
        items = [item for item in items if item["priority"]["score"] >= score_min]
    if score_max is not None:
        items = [item for item in items if item["priority"]["score"] <= score_max]
    if score_level:
        items = [item for item in items if item["priority"]["level"] == score_level]
    if sort == "score_desc":
        items.sort(key=lambda item: (-item["priority"]["score"], -item["id"]))
    return {
        "items": items,
        "next_cursor": profiles[-1].id if len(rows) > limit and profiles else None,
        "has_more": len(rows) > limit,
    }


@router.get("/{profile_id}")
async def get_profile(
    profile_id: int,
    message_cursor: int | None = None,
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    profile = await session.get(TransportProfile, profile_id)
    if profile is None:
        raise HTTPException(404, "Profile not found")
    identifiers = (
        await session.scalars(
            select(ProfileIdentifier).where(ProfileIdentifier.profile_id == profile_id)
        )
    ).all()
    occurrence_query = (
        select(ProfileOccurrence, TelegramMessage)
        .join(TelegramMessage)
        .where(ProfileOccurrence.profile_id == profile_id)
        .order_by(TelegramMessage.published_at.desc())
        .limit(limit + 1)
    )
    if message_cursor:
        occurrence_query = occurrence_query.where(TelegramMessage.id < message_cursor)
    occurrences = (await session.execute(occurrence_query)).all()
    vehicles = (
        await session.execute(
            select(Vehicle, ProfileVehicleLink)
            .join(ProfileVehicleLink)
            .where(ProfileVehicleLink.profile_id == profile_id)
        )
    ).all()
    relations = (
        await session.scalars(
            select(ProfileRelation).where(
                or_(
                    ProfileRelation.left_profile_id == profile_id,
                    ProfileRelation.right_profile_id == profile_id,
                )
            )
        )
    ).all()
    conflicts = (
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
    routes = (
        await session.execute(
            select(
                MessageRoute.normalized_origin, MessageRoute.normalized_destination, func.count()
            )
            .join(MessageAnalysis)
            .join(TelegramMessage)
            .join(ProfileOccurrence, ProfileOccurrence.message_id == TelegramMessage.id)
            .where(ProfileOccurrence.profile_id == profile_id)
            .group_by(MessageRoute.normalized_origin, MessageRoute.normalized_destination)
        )
    ).all()
    priority = (await scores_for_profiles(session, [profile_id], generated_at=datetime.now(timezone.utc)))[profile_id]
    return {
        "profile": model_data(
            profile,
            (
                "id",
                "profile_kind",
                "canonical_label",
                "status",
                "first_seen_at",
                "last_seen_at",
                "occurrence_count",
                "active_occurrence_count",
                "resolver_version",
            ),
        ),
        "priority": priority,
        "identifiers": [
            model_data(
                item,
                (
                    "id",
                    "identifier_type",
                    "identifier_role",
                    "raw_value",
                    "normalized_value",
                    "confidence",
                    "first_seen_at",
                    "last_seen_at",
                    "occurrence_count",
                ),
            )
            for item in identifiers
        ],
        "vehicles": [
            {
                "vehicle": model_data(
                    vehicle,
                    (
                        "id",
                        "identity_kind",
                        "normalized_plate",
                        "make",
                        "model",
                        "generation",
                        "year",
                        "canonical_label",
                        "first_seen_at",
                        "last_seen_at",
                        "observation_count",
                    ),
                ),
                "link": model_data(
                    link,
                    ("first_seen_at", "last_seen_at", "occurrence_count", "confidence", "evidence"),
                ),
            }
            for vehicle, link in vehicles
        ],
        "routes": [
            {"origin": origin, "destination": destination, "count": count}
            for origin, destination, count in routes
        ],
        "relations": [
            model_data(
                item,
                (
                    "id",
                    "left_profile_id",
                    "right_profile_id",
                    "relation_type",
                    "confidence",
                    "first_seen_at",
                    "last_seen_at",
                    "occurrence_count",
                    "evidence",
                ),
            )
            for item in relations
        ],
        "conflicts": [
            model_data(
                item, ("id", "message_id", "conflict_type", "status", "details", "created_at")
            )
            for item in conflicts
        ],
        "occurrences": [
            {
                "occurrence": model_data(
                    occurrence,
                    (
                        "match_method",
                        "confidence",
                        "evidence",
                        "source_deleted",
                        "first_seen_at",
                        "last_resolved_at",
                    ),
                ),
                "message": model_data(
                    message, ("id", "telegram_message_id", "text", "published_at", "is_deleted")
                ),
            }
            for occurrence, message in occurrences[:limit]
        ],
        "next_message_cursor": occurrences[-1][1].id if len(occurrences) > limit else None,
        "disclaimer": "Профиль построен автоматически по публичным объявлениям и не подтверждает личность человека или право собственности на автомобиль.",
    }


@vehicles_router.get("")
async def list_vehicles(
    plate: str | None = None,
    make: str | None = None,
    model: str | None = None,
    year: int | None = None,
    profile_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    filters = []
    if plate:
        filters.append(Vehicle.normalized_plate.ilike(f"%{plate}%"))
    if make:
        filters.append(Vehicle.make.ilike(f"%{make}%"))
    if model:
        filters.append(Vehicle.model.ilike(f"%{model}%"))
    if year:
        filters.append(Vehicle.year == year)
    if profile_id:
        filters.append(
            Vehicle.id.in_(
                select(ProfileVehicleLink.vehicle_id).where(
                    ProfileVehicleLink.profile_id == profile_id
                )
            )
        )
    vehicles = list(
        (
            await session.scalars(
                select(Vehicle).where(*filters).order_by(Vehicle.last_seen_at.desc()).limit(100)
            )
        ).all()
    )
    return [
        model_data(
            item,
            (
                "id",
                "identity_kind",
                "normalized_plate",
                "make",
                "model",
                "generation",
                "year",
                "canonical_label",
                "first_seen_at",
                "last_seen_at",
                "observation_count",
            ),
        )
        for item in vehicles
    ]


@vehicles_router.get("/{vehicle_id}")
async def get_vehicle(
    vehicle_id: int, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    vehicle = await session.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(404, "Vehicle not found")
    observations = (
        await session.execute(
            select(VehicleObservation, TelegramMessage)
            .join(TelegramMessage)
            .where(VehicleObservation.vehicle_id == vehicle_id)
            .order_by(TelegramMessage.published_at.desc())
        )
    ).all()
    profiles = (
        await session.execute(
            select(TransportProfile, ProfileVehicleLink)
            .join(ProfileVehicleLink)
            .where(ProfileVehicleLink.vehicle_id == vehicle_id)
        )
    ).all()
    return {
        "vehicle": model_data(
            vehicle,
            (
                "id",
                "identity_kind",
                "normalized_plate",
                "make",
                "model",
                "generation",
                "year",
                "canonical_label",
                "first_seen_at",
                "last_seen_at",
                "observation_count",
            ),
        ),
        "observations": [
            {
                "observation": model_data(
                    observation,
                    (
                        "id",
                        "message_id",
                        "profile_id",
                        "source_type",
                        "extracted_entity_id",
                        "plate_detection_id",
                        "confidence",
                        "evidence",
                    ),
                ),
                "message": model_data(
                    message, ("id", "telegram_message_id", "text", "published_at", "is_deleted")
                ),
            }
            for observation, message in observations
        ],
        "profiles": [
            {
                "profile": model_data(profile, ("id", "canonical_label", "profile_kind")),
                "link": model_data(
                    link,
                    ("first_seen_at", "last_seen_at", "occurrence_count", "confidence", "evidence"),
                ),
            }
            for profile, link in profiles
        ],
    }
