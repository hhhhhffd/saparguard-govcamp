"""Export reviewed annotations without mutating production data."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database.models import MessageAnnotation
from app.database.session import SessionFactory

PHONE_IN_TEXT = re.compile(r"(?<!\d)(?:\+?\d[\d\s()\-]{7,}\d)(?!\d)")


def mask_phones(text: str) -> str:
    return PHONE_IN_TEXT.sub("[PHONE]", text)


async def export(output_dir: Path, min_reviewed: int, include_sensitive_values: bool) -> Path:
    async with SessionFactory() as session:
        query = (
            select(MessageAnnotation)
            .where(MessageAnnotation.status == "reviewed")
            .options(
                selectinload(MessageAnnotation.message),
                selectinload(MessageAnnotation.phones),
                selectinload(MessageAnnotation.routes),
                selectinload(MessageAnnotation.vehicles),
            )
        )
        annotations = list((await session.scalars(query)).all())
    if len(annotations) < min_reviewed:
        raise ValueError(
            f"Need at least {min_reviewed} reviewed annotations; found {len(annotations)}"
        )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_dir = output_dir / f"human-reviewed-{stamp}"
    export_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    for annotation in annotations:
        expected = {
            "message_type": annotation.expected_message_type,
            "routes": [
                {"origin": value.normalized_origin, "destination": value.normalized_destination}
                for value in annotation.routes
            ],
            "vehicles": [value.normalized_value for value in annotation.vehicles],
        }
        if include_sensitive_values:
            expected["phones"] = [value.normalized_value for value in annotation.phones]
        rows.append(
            {
                "reference": f"message:{annotation.message_id}",
                "text": annotation.message.text or "",
                "expected": expected,
            }
            if include_sensitive_values
            else {
                "reference": f"message:{annotation.message_id}",
                "text": mask_phones(annotation.message.text or ""),
                "expected": expected,
            }
        )
    (export_dir / "reviewed.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    metadata = {
        "schema_version": "1",
        "annotation_status": "reviewed",
        "annotated_by": sorted({item.annotator for item in annotations}),
        "reviewed_by_human": True,
        "dataset_type": "human_reviewed",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "example_count": len(rows),
        "sensitive_values_included": include_sensitive_values,
    }
    (export_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return export_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-reviewed", type=int, default=1)
    parser.add_argument("--include-sensitive-values", action="store_true")
    args = parser.parse_args()
    asyncio.run(export(args.output_dir, args.min_reviewed, args.include_sensitive_values))


if __name__ == "__main__":
    main()
