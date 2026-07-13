from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResolutionInput:
    message_id: int
    is_deleted: bool
    sender_id: int | None
    message_type: str | None
    phones: tuple[tuple[int, str, str, float], ...]
    vehicles: tuple[tuple[int, dict[str, object], float], ...]
    plates: tuple[tuple[int, str, float | None], ...]
