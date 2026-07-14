"""Bounded relationship graph endpoints backed only by persisted evidence."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ProfileRelation, ProfileVehicleLink, TransportProfile, Vehicle
from app.database.session import get_session

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("")
async def get_graph(
    limit: int = Query(100, ge=1, le=200),
    profile_id: int | None = None,
    vehicle_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return a deliberately capped graph and disclose when it is truncated."""
    profile_statement = (
        select(TransportProfile).order_by(TransportProfile.last_seen_at.desc()).limit(limit)
    )
    if profile_id is not None:
        profile_statement = select(TransportProfile).where(TransportProfile.id == profile_id)
    if vehicle_id is not None:
        profile_statement = (
            select(TransportProfile)
            .join(ProfileVehicleLink)
            .where(ProfileVehicleLink.vehicle_id == vehicle_id)
            .limit(limit)
        )
    profiles = list((await session.scalars(profile_statement)).all())
    profile_ids = [profile.id for profile in profiles]
    links = (
        list(
            (
                await session.execute(
                    select(ProfileVehicleLink, Vehicle)
                    .join(Vehicle)
                    .where(ProfileVehicleLink.profile_id.in_(profile_ids))
                )
            ).all()
        )
        if profile_ids
        else []
    )
    vehicles = {vehicle.id: vehicle for _, vehicle in links}
    relations = (
        list(
            (
                await session.scalars(
                    select(ProfileRelation).where(
                        or_(
                            ProfileRelation.left_profile_id.in_(profile_ids),
                            ProfileRelation.right_profile_id.in_(profile_ids),
                        )
                    )
                )
            ).all()
        )
        if profile_ids
        else []
    )
    nodes = [
        {
            "data": {
                "id": f"p-{item.id}",
                "label": item.canonical_label,
                "type": "profile",
                "url": f"/profiles/{item.id}",
            }
        }
        for item in profiles
    ]
    nodes.extend(
        {
            "data": {
                "id": f"v-{item.id}",
                "label": item.normalized_plate or item.canonical_label,
                "type": "vehicle",
                "url": f"/vehicles/{item.id}",
            }
        }
        for item in vehicles.values()
    )
    edges = [
        {
            "data": {
                "id": f"pv-{link.profile_id}-{link.vehicle_id}",
                "source": f"p-{link.profile_id}",
                "target": f"v-{link.vehicle_id}",
                "type": "profile_vehicle",
                "evidence": link.evidence,
            }
        }
        for link, _ in links
    ]
    edges.extend(
        {
            "data": {
                "id": f"pr-{item.id}",
                "source": f"p-{item.left_profile_id}",
                "target": f"p-{item.right_profile_id}",
                "type": item.relation_type,
                "evidence": item.evidence,
            }
        }
        for item in relations
        if item.left_profile_id in profile_ids and item.right_profile_id in profile_ids
    )
    return {
        "elements": {"nodes": nodes, "edges": edges},
        "truncated": len(profiles) >= limit,
        "limit": limit,
    }
