from __future__ import annotations

import json

import pytest

from app.evaluation.cli import run
from app.evaluation.datasets import dataset_metadata
from app.evaluation.metrics import entity_metrics
from app.review.service import normalize_annotation_values, stratified_sample


def test_annotation_values_are_normalized_and_deduplicated() -> None:
    phones, routes, vehicles = normalize_annotation_values(
        ["8 702 000 71 23\n+77020007123"],
        [" Алматы -> Бишкек ", "Алматы -> Бишкек"],
        ["toyota   camry 70", "Toyota Camry 70"],
    )
    assert phones == ["+77020007123"]
    assert routes == [("алматы", "бишкек")]
    assert vehicles == ["TOYOTA CAMRY 70"]


def test_annotation_rejects_invalid_route_and_phone() -> None:
    with pytest.raises(ValueError):
        normalize_annotation_values(["123"], [], [])
    with pytest.raises(ValueError):
        normalize_annotation_values([], ["Алматы Бишкек"], [])


def test_entity_metric_is_not_reported_for_empty_sample() -> None:
    metrics = entity_metrics([], [])
    assert metrics["precision"] is None
    assert metrics["f1"] is None


def test_stratified_sampling_is_reproducible_and_balanced() -> None:
    rows = [
        (1, 10, "driver_offer", 0.9, "short"),
        (2, 10, "driver_offer", 0.9, "another"),
        (3, 11, "passenger_request", 0.2, "x" * 600),
    ]
    first = stratified_sample(rows, limit=2, seed=42)
    assert first == stratified_sample(rows, limit=2, seed=42)
    assert len(first) == 2
    assert 3 in first


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
