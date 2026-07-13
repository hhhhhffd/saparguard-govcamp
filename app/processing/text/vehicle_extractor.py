from __future__ import annotations

import re

from app.processing.text.data.vehicles import VEHICLE_ALIASES
from app.processing.text.models import EntityResult

GENERATION_PATTERN = r"(?:50|55|70|w220)"
YEAR_PATTERN = r"(?:19[89]\d|20[0-2]\d)"


def extract_vehicles(text: str | None) -> list[EntityResult]:
    value = text or ""
    results: list[EntityResult] = []
    seen: set[tuple[int, str]] = set()
    for make, details in VEHICLE_ALIASES.items():
        model_aliases = {
            alias: model for model, aliases in details["models"].items() for alias in aliases
        }
        prefixes = [*details["aliases"], *model_aliases]
        for prefix in prefixes:
            pattern = re.compile(
                rf"(?<!\w)({re.escape(prefix)})(?:\s+({GENERATION_PATTERN}))?(?:\s+({YEAR_PATTERN}))?(?!\w)",
                re.IGNORECASE,
            )
            for match in pattern.finditer(value):
                model = model_aliases.get(prefix.casefold())
                if model is None and match.group(1).casefold() in model_aliases:
                    model = model_aliases[match.group(1).casefold()]
                generation = match.group(2)
                year = match.group(3)
                fragment = match.group(0)
                key = (match.start(), fragment.casefold())
                if key in seen:
                    continue
                seen.add(key)
                metadata: dict[str, object] = {"make": make}
                if model:
                    metadata["model"] = model
                if generation:
                    metadata["generation"] = generation.upper()
                if year:
                    metadata["year"] = int(year)
                normalized = " ".join(
                    filter(None, (make, model, generation.upper() if generation else None))
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
