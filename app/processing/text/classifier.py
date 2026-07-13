from __future__ import annotations

import re

from app.processing.text.models import ClassificationResult

RULES = (
    (
        "service_message",
        0.96,
        (
            r"добав.{0,12}человек",
            r"группага.{0,20}кош",
            r"\b(?:spam|lols)?bot\b",
            r"\bбот(?:ом|а|ы)?\b",
            r"нажмите.{0,20}бот",
            r"заблокир",
        ),
    ),
    ("commercial_spam", 0.98, (r"\busdt\b", r"\btrc20\b", r"продам аккаунт", r"продажа аккаунт")),
    ("parcel_request", 0.88, (r"доставить.{0,20}посыл", r"посыл.{0,20}(сколько|нужн|отправ)")),
    (
        "parcel_offer",
        0.87,
        (
            r"(достав|отправ).{0,20}посыл",
            r"посылк.{0,20}(бер|приним|алам)",
            r"(бер|приним|алам).{0,20}посыл",
            r"от двери до двери.{0,20}посыл",
        ),
    ),
    (
        "passenger_request",
        0.84,
        (r"такси керек", r"ищу.{0,20}(такси|водител)", r"нужно.{0,20}(такси|мест)"),
    ),
    (
        "driver_offer",
        0.82,
        (
            r"\bтакси\b",
            r"еду.{0,30}(алмат|бишк|астан|тараз)",
            r"места? есть",
            r"выезд",
            r"(?:алмат|бишк|астан|тараз).{0,30}(?:алмат|бишк|астан|тараз).{0,40}\+?7\d{10}",
        ),
    ),
)
ATTRIBUTES = {
    "accepts_parcels": (
        r"посыл.{0,12}(бер|приним|достав|алам)",
        r"(бер|приним|достав|алам).{0,12}посыл",
    ),
    "airport_transfer": (r"аэропорт",),
    "door_to_door": (r"от двери до двери|дверь до двер|от адреса до адреса",),
    "available_24_7": (r"24.?7|круглосуточ",),
}


def classify(text: str | None) -> ClassificationResult:
    value = (text or "").casefold()
    scores: dict[str, tuple[float, list[str]]] = {}
    for message_type, confidence, patterns in RULES:
        matches = [pattern for pattern in patterns if re.search(pattern, value)]
        if matches:
            scores[message_type] = (confidence, matches)
    attributes = {
        key: True
        for key, patterns in ATTRIBUTES.items()
        if any(re.search(p, value) for p in patterns)
    }
    if not value.strip():
        return ClassificationResult("unknown", 1.0, ("empty_text",), attributes)
    if scores:
        if "driver_offer" in scores and attributes.get("accepts_parcels"):
            confidence, evidence = scores["driver_offer"]
            return ClassificationResult(
                "driver_offer",
                max(confidence, 0.9),
                tuple([*evidence, "accepts_parcels"]),
                attributes,
            )
        message_type, (confidence, evidence) = max(scores.items(), key=lambda item: item[1][0])
        return ClassificationResult(message_type, confidence, tuple(evidence), attributes)
    if len(value.split()) <= 5:
        return ClassificationResult("conversation", 0.55, ("short_unstructured_text",), attributes)
    return ClassificationResult("unknown", 0.4, ("no_rule_matched",), attributes)
