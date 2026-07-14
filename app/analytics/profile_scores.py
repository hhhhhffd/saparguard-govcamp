"""Batch loading of persisted facts required by profile priority scores."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.priority_score import PriorityScoreInput, calculate_priority_score
from app.database.models import (
    MessageAnalysis,
    MessageRoute,
    ProfileIdentifier,
    ProfileOccurrence,
    ProfileRelation,
    ProfileResolutionConflict,
    ProfileVehicleLink,
    ProfileVehicleLinkObservation,
    TelegramMessage,
    Vehicle,
)


async def scores_for_profiles(
    session: AsyncSession, profile_ids: list[int], *, generated_at: datetime
) -> dict[int, dict[str, Any]]:
    """Calculate score inputs in fixed aggregate queries, never per profile."""
    if not profile_ids:
        return {}
    cutoff = generated_at - timedelta(days=7)
    occurrences = (
        select(
            ProfileOccurrence.profile_id,
            func.count(ProfileOccurrence.id).filter(TelegramMessage.published_at >= cutoff).label("recent"),
            func.count(func.distinct(TelegramMessage.telegram_chat_id))
            .filter(TelegramMessage.published_at >= cutoff)
            .label("sources"),
        )
        .join(TelegramMessage, TelegramMessage.id == ProfileOccurrence.message_id)
        .where(ProfileOccurrence.profile_id.in_(profile_ids), ProfileOccurrence.source_deleted.is_(False))
        .group_by(ProfileOccurrence.profile_id)
    )
    identifiers = (
        select(
            ProfileIdentifier.profile_id,
            func.bool_or(ProfileIdentifier.identifier_type == "phone").label("phone"),
            func.bool_or(ProfileIdentifier.identifier_type.in_(("telegram_user_id", "telegram_username"))).label("telegram"),
        )
        .where(ProfileIdentifier.profile_id.in_(profile_ids))
        .group_by(ProfileIdentifier.profile_id)
    )
    routes = (
        select(ProfileOccurrence.profile_id, func.count(func.distinct(MessageRoute.id)).label("routes"))
        .join(TelegramMessage, TelegramMessage.id == ProfileOccurrence.message_id)
        .join(MessageAnalysis, MessageAnalysis.message_id == TelegramMessage.id)
        .join(MessageRoute, MessageRoute.analysis_id == MessageAnalysis.id)
        .where(ProfileOccurrence.profile_id.in_(profile_ids))
        .group_by(ProfileOccurrence.profile_id)
    )
    vehicles = (
        select(
            ProfileVehicleLink.profile_id,
            func.count(func.distinct(ProfileVehicleLink.vehicle_id)).label("vehicles"),
            func.count(func.distinct(Vehicle.normalized_plate)).label("plates"),
        )
        .join(Vehicle, Vehicle.id == ProfileVehicleLink.vehicle_id)
        .where(ProfileVehicleLink.profile_id.in_(profile_ids))
        .group_by(ProfileVehicleLink.profile_id)
    )
    relations = (
        select(
            ProfileVehicleLinkObservation.profile_id,
            func.count(func.distinct(ProfileVehicleLinkObservation.message_id)).label("links"),
        )
        .where(ProfileVehicleLinkObservation.profile_id.in_(profile_ids))
        .group_by(ProfileVehicleLinkObservation.profile_id)
    )
    related = (
        select(
            ProfileRelation.left_profile_id.label("profile_id"),
            func.count(ProfileRelation.id).label("relations"),
        )
        .where(ProfileRelation.left_profile_id.in_(profile_ids))
        .group_by(ProfileRelation.left_profile_id)
        .union_all(
            select(
                ProfileRelation.right_profile_id.label("profile_id"),
                func.count(ProfileRelation.id).label("relations"),
            )
            .where(ProfileRelation.right_profile_id.in_(profile_ids))
            .group_by(ProfileRelation.right_profile_id)
        )
        .subquery()
    )
    conflict_query = (
        select(ProfileOccurrence.profile_id, func.count(func.distinct(ProfileResolutionConflict.id)))
        .join(ProfileResolutionConflict, ProfileResolutionConflict.message_id == ProfileOccurrence.message_id)
        .where(ProfileOccurrence.profile_id.in_(profile_ids), ProfileResolutionConflict.status == "open")
        .group_by(ProfileOccurrence.profile_id)
    )

    async def keyed(statement: Any) -> dict[int, Any]:
        return {row[0]: row[1:] for row in (await session.execute(statement)).all()}

    occurrence_values, identifier_values, route_values, vehicle_values, link_values, conflict_values = (
        await keyed(occurrences),
        await keyed(identifiers),
        await keyed(routes),
        await keyed(vehicles),
        await keyed(relations),
        await keyed(conflict_query),
    )
    relation_values = {
        profile_id: sum(int(row[0]) for row in rows)
        for profile_id, rows in _group_rows((await session.execute(select(related))).all()).items()
    }
    profile_last_seen = dict(
        (await session.execute(select(ProfileOccurrence.profile_id, func.max(ProfileOccurrence.first_seen_at)).where(ProfileOccurrence.profile_id.in_(profile_ids)).group_by(ProfileOccurrence.profile_id))).all()
    )
    result: dict[int, dict[str, Any]] = {}
    for profile_id in profile_ids:
        recent, sources = occurrence_values.get(profile_id, (0, 0))
        phone, telegram = identifier_values.get(profile_id, (False, False))
        route_count = route_values.get(profile_id, (0,))[0]
        vehicle_count, plate_count = vehicle_values.get(profile_id, (0, 0))
        link_count = link_values.get(profile_id, (0,))[0]
        conflict_count = conflict_values.get(profile_id, (0,))[0]
        result[profile_id] = calculate_priority_score(
            PriorityScoreInput(
                last_seen_at=profile_last_seen.get(profile_id),
                occurrences_last_7_days=int(recent or 0),
                source_count_last_7_days=int(sources or 0),
                has_phone=bool(phone), has_telegram_identity=bool(telegram), has_route=bool(route_count),
                vehicle_count=int(vehicle_count or 0), plate_count=int(plate_count or 0),
                related_profile_count=relation_values.get(profile_id, 0),
                link_observation_count=int(link_count or 0), conflict_count=int(conflict_count or 0),
            ),
            generated_at=generated_at,
        )
    return result


def _group_rows(rows: list[Any]) -> dict[int, list[Any]]:
    grouped: dict[int, list[Any]] = {}
    for row in rows:
        grouped.setdefault(row[0], []).append(row[1:])
    return grouped
