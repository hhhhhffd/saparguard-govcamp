from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EntityResult:
    entity_type: str
    raw_value: str
    normalized_value: str
    confidence: float
    evidence: str
    role: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RouteResult:
    raw_origin: str
    normalized_origin: str
    raw_destination: str
    normalized_destination: str
    confidence: float
    evidence: str


@dataclass(frozen=True)
class ClassificationResult:
    message_type: str
    confidence: float
    evidence: tuple[str, ...]
    attributes: dict[str, bool]


@dataclass(frozen=True)
class AnalysisResult:
    classification: ClassificationResult
    entities: tuple[EntityResult, ...]
    routes: tuple[RouteResult, ...]
