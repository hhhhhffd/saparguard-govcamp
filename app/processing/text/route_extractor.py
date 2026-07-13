from __future__ import annotations

import re

from app.processing.text.data.locations import LOCATION_ALIASES
from app.processing.text.models import EntityResult, RouteResult


def extract_routes_and_locations(text: str | None) -> tuple[list[EntityResult], list[RouteResult]]:
    value = text or ""
    locations: list[EntityResult] = []
    aliases: list[tuple[int, int, str, str]] = []
    for canonical, names in LOCATION_ALIASES.items():
        for name in names:
            for match in re.finditer(
                r"(?<!\w)" + re.escape(name) + r"(?:[а-яөүіңқғ]{0,3})?(?!\w)", value, re.I
            ):
                aliases.append((match.start(), match.end(), canonical, match.group(0)))
    aliases.sort()
    seen: set[tuple[str, int]] = set()
    for start, end, canonical, raw in aliases:
        if (canonical, start) not in seen:
            locations.append(
                EntityResult(
                    "location", raw, canonical, 0.9, "location_alias", "mentioned", start, end
                )
            )
            seen.add((canonical, start))
    routes: list[RouteResult] = []
    direction = re.compile(
        r"(?:из|с|откуда\s*:)\s*([^\n,;]+?)\s*(?:в|до|куда\s*:|→|-)\s*([^\n,;]+)", re.I
    )
    for match in direction.finditer(value):
        candidates = [item for item in aliases if match.start() <= item[0] <= match.end()]
        if len(candidates) >= 2:
            first, last = candidates[0], candidates[-1]
            if first[2] != last[2]:
                routes.append(
                    RouteResult(first[3], first[2], last[3], last[2], 0.9, "explicit_direction")
                )
    if not routes and len(aliases) == 2 and re.search(r"(?:→|↔|\s-\s|такси керек)", value, re.I):
        first, last = aliases
        if first[2] != last[2]:
            routes.append(RouteResult(first[3], first[2], last[3], last[2], 0.76, "route_pair"))
            if "↔" in value:
                routes.append(
                    RouteResult(
                        last[3], last[2], first[3], first[2], 0.76, "bidirectional_route_pair"
                    )
                )
    return locations, routes
