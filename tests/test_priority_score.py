from datetime import datetime, timedelta, timezone

from app.analytics.priority_score import (
    PriorityScoreInput,
    calculate_priority_score,
    priority_level,
)


NOW = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)


def input_for(**changes: object) -> PriorityScoreInput:
    values: dict[str, object] = {
        "last_seen_at": None,
        "occurrences_last_7_days": 0,
        "source_count_last_7_days": 0,
        "has_phone": False,
        "has_telegram_identity": False,
        "has_route": False,
        "vehicle_count": 0,
        "plate_count": 0,
        "related_profile_count": 0,
        "link_observation_count": 0,
        "conflict_count": 0,
    }
    values.update(changes)
    return PriorityScoreInput(**values)  # type: ignore[arg-type]


def test_priority_score_is_bounded_and_deterministic() -> None:
    value = input_for(
        last_seen_at=NOW,
        occurrences_last_7_days=100,
        source_count_last_7_days=99,
        has_phone=True,
        has_telegram_identity=True,
        has_route=True,
        vehicle_count=99,
        plate_count=99,
        related_profile_count=99,
        link_observation_count=99,
        conflict_count=99,
    )
    first = calculate_priority_score(value, generated_at=NOW)
    assert first == calculate_priority_score(value, generated_at=NOW)
    assert first["score"] == 100
    assert all(factor["points"] <= factor["max_points"] for factor in first["factors"])


def test_freshness_boundaries() -> None:
    assert (
        calculate_priority_score(
            input_for(last_seen_at=NOW - timedelta(hours=24)), generated_at=NOW
        )["factors"][0]["points"]
        == 10
    )
    assert (
        calculate_priority_score(input_for(last_seen_at=NOW - timedelta(days=3)), generated_at=NOW)[
            "factors"
        ][0]["points"]
        == 7
    )
    assert (
        calculate_priority_score(input_for(last_seen_at=NOW - timedelta(days=7)), generated_at=NOW)[
            "factors"
        ][0]["points"]
        == 4
    )
    assert (
        calculate_priority_score(
            input_for(last_seen_at=NOW - timedelta(days=7, seconds=1)), generated_at=NOW
        )["factors"][0]["points"]
        == 0
    )


def test_levels_cover_boundaries() -> None:
    assert [priority_level(value) for value in (0, 24, 25, 49, 50, 74, 75, 100)] == [
        "low",
        "low",
        "medium",
        "medium",
        "high",
        "high",
        "very_high",
        "very_high",
    ]
