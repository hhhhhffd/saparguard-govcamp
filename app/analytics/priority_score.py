"""Deterministic, explainable priority calculation for transport profiles.

The result is deliberately a review-priority signal, not a risk assessment or
an assertion about a person.  Inputs are pre-aggregated persisted facts so the
calculation is independent from database row ordering.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

PriorityLevel = Literal["low", "medium", "high", "very_high"]


@dataclass(frozen=True)
class PriorityScoreInput:
    last_seen_at: datetime | None
    occurrences_last_7_days: int
    source_count_last_7_days: int
    has_phone: bool
    has_telegram_identity: bool
    has_route: bool
    vehicle_count: int
    plate_count: int
    related_profile_count: int
    link_observation_count: int
    conflict_count: int


def priority_level(score: int) -> PriorityLevel:
    if score < 25:
        return "low"
    if score < 50:
        return "medium"
    if score < 75:
        return "high"
    return "very_high"


def _factor(code: str, points: int, maximum: int, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "points": points, "max_points": maximum, "evidence": evidence}


def calculate_priority_score(
    values: PriorityScoreInput, *, generated_at: datetime
) -> dict[str, Any]:
    """Return a capped 0–100 priority and evidence for every score factor."""
    recent_cutoffs = {
        "24h": generated_at - timedelta(hours=24),
        "3d": generated_at - timedelta(days=3),
        "7d": generated_at - timedelta(days=7),
    }
    if values.last_seen_at is None:
        freshness = 0
    elif values.last_seen_at >= recent_cutoffs["24h"]:
        freshness = 10
    elif values.last_seen_at >= recent_cutoffs["3d"]:
        freshness = 7
    elif values.last_seen_at >= recent_cutoffs["7d"]:
        freshness = 4
    else:
        freshness = 0

    repeatability = (
        0
        if values.occurrences_last_7_days == 0
        else min(15, 3 + 3 * (values.occurrences_last_7_days - 1))
    )
    source_points = min(20, values.source_count_last_7_days * 7)
    identifiers = (
        (4 if values.has_phone else 0)
        + (3 if values.has_telegram_identity else 0)
        + (3 if values.has_route else 0)
        + (3 if values.vehicle_count else 0)
        + (2 if values.plate_count else 0)
    )
    connections = min(
        20,
        values.vehicle_count * 4
        + values.related_profile_count * 4
        + min(8, values.link_observation_count * 2),
    )
    conflicts = min(20, values.conflict_count * 10)
    factors = [
        _factor("recent_activity", freshness, 10, {"last_seen_at": values.last_seen_at}),
        _factor(
            "repeat_activity",
            repeatability,
            15,
            {"occurrences_last_7_days": values.occurrences_last_7_days},
        ),
        _factor(
            "independent_sources",
            source_points,
            20,
            {"sources_last_7_days": values.source_count_last_7_days},
        ),
        _factor(
            "identifier_completeness",
            identifiers,
            15,
            {
                "phone": values.has_phone,
                "telegram_identity": values.has_telegram_identity,
                "route": values.has_route,
                "vehicles": values.vehicle_count,
                "plates": values.plate_count,
            },
        ),
        _factor(
            "connections",
            connections,
            20,
            {
                "vehicles": values.vehicle_count,
                "related_profiles": values.related_profile_count,
                "link_observations": values.link_observation_count,
            },
        ),
        _factor("resolution_conflicts", conflicts, 20, {"conflicts": values.conflict_count}),
    ]
    score = min(100, sum(item["points"] for item in factors))
    return {
        "score": score,
        "level": priority_level(score),
        "factors": factors,
        "generated_at": generated_at,
        "input": asdict(values),
    }
