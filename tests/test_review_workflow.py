from __future__ import annotations

import json

import pytest

from app.review import service as review_service
from app.evaluation.cli import _component, run
from app.evaluation.datasets import dataset_metadata
from app.evaluation.metrics import entity_metrics
from app.review.service import (
    normalize_annotation_values,
    normalize_phone,
    normalize_route,
    normalize_vehicle,
    ReviewFilters,
    select_review_queue,
    source_text_hash,
    stratified_sample,
)


def test_annotation_values_are_normalized_and_deduplicated() -> None:
    phones, routes, vehicles = normalize_annotation_values(
        ["8 702 000 71 23\n+77020007123"],
        [" Алматы -> Бишкек ", "Алматы -> Бишкек"],
        ["toyota   camry 70", "Toyota Camry 70"],
    )
    assert phones == ["+77020007123"]
    assert routes == [("алматы", "бишкек")]
    assert vehicles == ["toyota camry 70"]


def test_annotation_rejects_invalid_route_and_phone() -> None:
    with pytest.raises(ValueError):
        normalize_annotation_values(["123"], [], [])
    with pytest.raises(ValueError):
        normalize_annotation_values([], ["Алматы Бишкек"], [])


@pytest.mark.parametrize("value", ["+7 702 000 71 23", "8 (707) 208-08-92", "+996 555 401 053"])
def test_phone_validation_accepts_supported_lengths(value: str) -> None:
    assert normalize_phone(value).startswith("+")


@pytest.mark.parametrize("value", ["+770200071234", "+99670012345", "+15551234567"])
def test_phone_validation_rejects_invalid_lengths_and_countries(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_phone(value)


def test_route_and_vehicle_normalization_matches_predictions() -> None:
    assert normalize_route("Алматы → Бишкек") == normalize_route(" алматы -> бишкек ")
    assert normalize_vehicle("Toyota Camry 70") == normalize_vehicle("TOYOTA   CAMRY 70")


def test_normalized_entity_metrics_have_no_false_results() -> None:
    rows = [{"text": "Toyota Camry 70 Алматы Бишкек", "expected": ["TOYOTA   CAMRY 70"]}]
    component = _component("vehicles", rows, "human_reviewed")
    assert component["metrics"]["precision"] == 1
    assert component["metrics"]["recall"] == 1
    assert component["metrics"]["f1"] == 1
    assert component["metrics"]["false_positives"] == 0
    assert component["metrics"]["false_negatives"] == 0


def test_entity_metric_is_not_reported_for_empty_sample() -> None:
    metrics = entity_metrics([], [])
    assert metrics["precision"] is None
    assert metrics["f1"] is None


def test_stratified_sampling_is_reproducible_and_balanced() -> None:
    rows = [
        (1, 10, "driver_offer", 0.9, "short", 1, False, False, False, False),
        (2, 10, "driver_offer", 0.9, "another", 2, False, False, False, False),
        (3, 11, "passenger_request", 0.2, "x" * 600, 0, False, False, False, False),
    ]
    first = stratified_sample(rows, limit=2, seed=42)
    assert first == stratified_sample(rows, limit=2, seed=42)
    assert len(first) == 2
    assert 3 in first


class ReviewQueueSession:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    async def execute(self, statement: object) -> object:
        del statement

        class Result:
            def __init__(self, rows: list[tuple[object, ...]]) -> None:
                self.rows = rows

            def all(self) -> list[tuple[object, ...]]:
                return self.rows

        return Result(self.rows)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("annotation_hash", "expected_ids"),
    [
        (source_text_hash("current text"), []),
        (source_text_hash("previous text"), [1]),
    ],
)
async def test_stale_review_queue_uses_annotation_hash(
    annotation_hash: str, expected_ids: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_rows: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        review_service,
        "stratified_sample",
        lambda rows, **_kwargs: captured_rows.extend(rows) or [row[0] for row in rows],
    )
    session = ReviewQueueSession(
        [(1, 10, "driver_offer", 0.9, "current text", 0, False, False, annotation_hash, False, True)]
    )

    result = await select_review_queue(session, ReviewFilters(annotation_status="stale"), limit=10, seed=1)

    assert result == expected_ids
    expected_rows = [
        (1, 10, "driver_offer", 0.9, "current text", 0, False, False, False, True)
    ] if expected_ids else []
    assert captured_rows == expected_rows


@pytest.mark.asyncio
@pytest.mark.parametrize("has_media, has_plate", [(False, True), (True, False)])
async def test_review_queue_preserves_media_and_plate_flags(
    has_media: bool, has_plate: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_rows: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        review_service,
        "stratified_sample",
        lambda rows, **_kwargs: captured_rows.extend(rows) or [row[0] for row in rows],
    )
    session = ReviewQueueSession(
        [
            (
                1,
                10,
                "driver_offer",
                0.9,
                "current text",
                0,
                False,
                False,
                source_text_hash("current text"),
                has_media,
                has_plate,
            )
        ]
    )

    result = await select_review_queue(session, ReviewFilters(), limit=10, seed=1)

    assert result == [1]
    assert captured_rows[0][-2:] == (has_media, has_plate)


def test_human_reviewed_dataset_cannot_claim_false_human_status(tmp_path) -> None:
    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "annotation_status": "reviewed",
                "annotated_by": "test",
                "reviewed_by_human": False,
                "dataset_type": "human_reviewed",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="explicitly reviewed"):
        dataset_metadata(tmp_path)


def test_synthetic_report_remains_separate(tmp_path) -> None:
    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "annotation_status": "draft",
                "annotated_by": "test",
                "reviewed_by_human": False,
                "dataset_type": "synthetic_draft",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "classification.jsonl").write_text(
        '{"text":"привет", "expected":"conversation"}\n', encoding="utf-8"
    )
    report = run(tmp_path, tmp_path / "reports")
    assert report["metadata"]["dataset_type"] == "synthetic_draft"
    assert any("не является" in warning for warning in report["warnings"])


def test_redacted_dataset_requires_explicit_override(tmp_path) -> None:
    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "annotation_status": "reviewed",
                "annotated_by": "test",
                "reviewed_by_human": True,
                "dataset_type": "human_reviewed",
                "redacted": True,
                "suitable_for_full_evaluation": False,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Redacted"):
        run(tmp_path, tmp_path / "reports")
