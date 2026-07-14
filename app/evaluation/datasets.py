"""Versioned JSONL dataset loading with strict validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_METADATA = {
    "schema_version",
    "annotation_status",
    "annotated_by",
    "reviewed_by_human",
    "dataset_type",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from error
        if not isinstance(value, dict) or "text" not in value or "expected" not in value:
            raise ValueError(f"{path}:{line_number}: text and expected are required")
        rows.append(value)
    return rows


def dataset_metadata(dataset_dir: Path) -> dict[str, Any]:
    metadata_path = dataset_dir / "metadata.json"
    if not metadata_path.exists():
        raise ValueError("metadata.json is required")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not REQUIRED_METADATA <= metadata.keys():
        raise ValueError("dataset metadata is incomplete")
    if metadata["dataset_type"] not in {"synthetic_draft", "human_reviewed"}:
        raise ValueError("dataset_type must be synthetic_draft or human_reviewed")
    if metadata["dataset_type"] == "human_reviewed" and not metadata["reviewed_by_human"]:
        raise ValueError("human_reviewed dataset must be explicitly reviewed by a human")
    return metadata
