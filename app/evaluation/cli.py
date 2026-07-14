from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.evaluation.datasets import dataset_metadata, load_jsonl
from app.evaluation.metrics import classification_metrics, entity_metrics
from app.processing.text.analyzer import analyze_message


def run(dataset_dir: Path, output_dir: Path) -> dict[str, object]:
    metadata = dataset_metadata(dataset_dir)
    components: dict[str, object] = {}
    for name in ("classification", "phones", "routes", "vehicles"):
        path = dataset_dir / f"{name}.jsonl"
        if not path.exists():
            components[name] = {"sample_size": 0, "status": "not evaluated", "primary_metric": None}
            continue
        rows = load_jsonl(path)
        analyses = [analyze_message(row["text"]) for row in rows]
        if name == "classification":
            metrics = classification_metrics(
                [row["expected"] for row in rows],
                [item.classification.message_type for item in analyses],
            )
            primary = metrics["macro_f1"]
        elif name == "routes":
            expected = [
                {f"{value['origin']}->{value['destination']}" for value in row["expected"]}
                for row in rows
            ]
            predicted = [
                {
                    f"{value.normalized_origin}->{value.normalized_destination}"
                    for value in item.routes
                }
                for item in analyses
            ]
            metrics = entity_metrics(expected, predicted)
            primary = metrics["f1"]
        else:
            entity_type = "phone" if name == "phones" else "vehicle"
            expected = [set(row["expected"]) for row in rows]
            predicted = [
                {
                    value.normalized_value
                    for value in item.entities
                    if value.entity_type == entity_type
                }
                for item in analyses
            ]
            metrics = entity_metrics(expected, predicted)
            primary = metrics["f1"]
        components[name] = {
            "sample_size": len(rows),
            "status": "draft",
            "primary_metric": {"name": "f1", "value": primary},
            "metrics": metrics,
        }
    for name in ("plates", "profile_pairs"):
        components[name] = {
            "sample_size": 0,
            "status": "not evaluated",
            "primary_metric": None,
            "limitation": "No independently annotated local image/pair dataset is available.",
        }
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata,
        "components": components,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (output_dir / f"evaluation-{stamp}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / f"evaluation-{stamp}.md").write_text(
        "# SaparGuard evaluation\n\n"
        + "\n".join(
            f"- {name}: n={item['sample_size']}, {item['status']}"
            for name, item in components.items()
        ),
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args.dataset_dir, args.output_dir)


if __name__ == "__main__":
    main()
