from __future__ import annotations

from app.processing.text.classifier import classify
from app.processing.text.models import AnalysisResult
from app.processing.text.phone_extractor import extract_phones
from app.processing.text.route_extractor import extract_routes_and_locations
from app.processing.text.vehicle_extractor import extract_vehicles


def analyze_message(text: str | None) -> AnalysisResult:
    """Analyze text without database, network, or mutable global state."""
    locations, routes = extract_routes_and_locations(text)
    entities = [*extract_phones(text), *locations, *extract_vehicles(text)]
    return AnalysisResult(classify(text), tuple(entities), tuple(routes))
