"""Read persisted offline evaluation reports without touching production data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_latest_report(reports_dir: Path = Path("evaluation/reports")) -> dict[str, Any] | None:
    reports = sorted(reports_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not reports:
        return None
    with reports[0].open(encoding="utf-8") as file:
        return json.load(file)
