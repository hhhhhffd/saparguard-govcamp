from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.evaluation.datasets import dataset_metadata, load_jsonl
from app.evaluation.metrics import classification_metrics, entity_metrics
from app.processing.text.analyzer import analyze_message
from app.review.service import (
    normalize_message_type,
    normalize_phone,
    normalize_route,
    normalize_vehicle,
)


def _errors(
    rows: list[dict[str, Any]], expected: list[set[str]], predicted: list[set[str]]
) -> list[dict[str, object]]:
    return [
        {
            "reference": row.get("reference", row.get("message_id")),
            "false_positives": sorted(guess - actual),
            "false_negatives": sorted(actual - guess),
        }
        for row, actual, guess in zip(rows, expected, predicted, strict=True)
        if actual != guess
    ]


def _component(name: str, rows: list[dict[str, Any]], status: str) -> dict[str, object]:
    if not rows:
        return {"sample_size": 0, "status": "not evaluated", "primary_metric": None}
    analyses = [analyze_message(row["text"]) for row in rows]
    if name == "classification":
        metrics = classification_metrics(
            [normalize_message_type(row["expected"]) for row in rows],
            [normalize_message_type(item.classification.message_type) for item in analyses],
        )
        warnings = [
            f"Class {label} is absent in ground truth"
            for label, item in metrics["per_class"].items()
            if item["support"] == 0
        ]
        return {
            "sample_size": len(rows),
            "status": status,
            "primary_metric": {"name": "macro_f1", "value": metrics["macro_f1"]},
            "metrics": metrics,
            "warnings": warnings,
        }
    if name == "routes":
        expected = [
            {
                "->".join(normalize_route(f"{value['origin']}->{value['destination']}"))
                for value in row["expected"]
            }
            for row in rows
        ]
        predicted = [
            {
                "->".join(
                    normalize_route(f"{value.normalized_origin}->{value.normalized_destination}")
                )
                for value in item.routes
            }
            for item in analyses
        ]
    else:
        entity_type = "phone" if name == "phones" else "vehicle"
        normalizer = normalize_phone if entity_type == "phone" else normalize_vehicle
        expected = [{normalizer(value) for value in row["expected"]} for row in rows]
        predicted = [
            {
                normalizer(value.normalized_value)
                for value in item.entities
                if value.entity_type == entity_type
            }
            for item in analyses
        ]
    metrics = entity_metrics(expected, predicted)
    return {
        "sample_size": len(rows),
        "status": status,
        "primary_metric": {"name": "f1", "value": metrics["f1"]},
        "metrics": metrics,
        "errors": _errors(rows, expected, predicted),
    }


def run(dataset_dir: Path, output_dir: Path, *, allow_redacted: bool = False) -> dict[str, object]:
    metadata = dataset_metadata(dataset_dir)
    if metadata.get("redacted") and not allow_redacted:
        raise ValueError(
            "Redacted dataset is not suitable for full evaluation; use sensitive export"
        )
    dataset_type = metadata["dataset_type"]
    components: dict[str, object] = {}
    reviewed_path = dataset_dir / "reviewed.jsonl"
    if reviewed_path.exists():
        rows = load_jsonl(reviewed_path)
        components["classification"] = _component(
            "classification",
            [
                {
                    "text": row["text"],
                    "expected": row["expected"]["message_type"],
                    "reference": row.get("reference"),
                }
                for row in rows
            ],
            dataset_type,
        )
        for name in ("phones", "routes", "vehicles"):
            items = [row for row in rows if name in row["expected"]]
            components[name] = _component(
                name,
                [
                    {
                        "text": row["text"],
                        "expected": row["expected"][name],
                        "reference": row.get("reference"),
                    }
                    for row in items
                ],
                dataset_type,
            )
    else:
        for name in ("classification", "phones", "routes", "vehicles"):
            path = dataset_dir / f"{name}.jsonl"
            components[name] = _component(
                name, load_jsonl(path) if path.exists() else [], dataset_type
            )
    warnings = []
    if dataset_type == "synthetic_draft":
        warnings.append("Synthetic smoke test — не является оценкой качества production data")
    if any(item["sample_size"] < 30 for item in components.values()):
        warnings.append("Выборка слишком мала для устойчивой оценки")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata,
        "components": components,
        "warnings": warnings,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (output_dir / f"evaluation-{stamp}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-redacted", action="store_true")
    args = parser.parse_args()
    run(args.dataset_dir, args.output_dir, allow_redacted=args.allow_redacted)


if __name__ == "__main__":
    main()
