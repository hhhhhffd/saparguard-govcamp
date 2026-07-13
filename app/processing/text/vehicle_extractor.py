from __future__ import annotations

import re

from app.processing.text.data.vehicles import VEHICLE_ALIASES
from app.processing.text.models import EntityResult


def extract_vehicles(text: str | None) -> list[EntityResult]:
    value = text or ""
    results: list[EntityResult] = []
    for make, details in VEHICLE_ALIASES.items():
        for alias in details["aliases"]:
            for match in re.finditer(
                r"(?<!\w)" + re.escape(alias) + r"(?!\w)(?:\s+([\w-]+))?", value, re.I
            ):
                fragment = match.group(0)
                model = None
                for canonical, aliases in details["models"].items():
                    if match.group(1) and match.group(1).casefold() in aliases:
                        model = canonical
                generation = re.search(r"\b(?:50|55|70|w220)\b", fragment, re.I)
                year = re.search(r"\b(19[89]\d|20[0-2]\d)\b", value[match.end() : match.end() + 12])
                metadata = {"make": make}
                if model:
                    metadata["model"] = model
                if generation:
                    metadata["generation"] = generation.group(0).upper()
                if year:
                    metadata["year"] = int(year.group(0))
                normalized = " ".join(
                    filter(None, (make, model, generation.group(0) if generation else None))
                )
                results.append(
                    EntityResult(
                        "vehicle",
                        fragment,
                        normalized,
                        0.92 if model else 0.72,
                        "vehicle_alias",
                        start_offset=match.start(),
                        end_offset=match.end(),
                        metadata=metadata,
                    )
                )
    return results
