from __future__ import annotations

import re

from app.processing.text.models import EntityResult

PHONE_PATTERN = re.compile(
    r"(?:(?:tel:|https?://(?:wa\.me|api\.whatsapp\.com/send\?phone=))?\s*)(\+?\d[\d\s()\-]{7,}\d)",
    re.I,
)


def _normalize(raw: str) -> tuple[str | None, float, dict[str, str]]:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("8"):
        return "+7" + digits[1:], 0.94, {"country": "KZ/RU", "normalization": "8_to_+7"}
    if len(digits) == 11 and digits.startswith("7"):
        return "+" + digits, 0.96, {"country": "KZ/RU", "normalization": "country_code"}
    if len(digits) == 12 and digits.startswith("996"):
        return "+" + digits, 0.97, {"country": "KG", "normalization": "country_code"}
    if len(digits) == 10 and digits.startswith(("70", "74", "75", "77")):
        return "+7" + digits, 0.72, {"country": "KZ", "normalization": "local_assumed"}
    if len(digits) == 9 and digits.startswith(("5", "7")):
        return "+996" + digits, 0.62, {"country": "KG", "normalization": "local_assumed"}
    return None, 0.0, {}


def extract_phones(text: str | None) -> list[EntityResult]:
    found: dict[str, EntityResult] = {}
    for match in PHONE_PATTERN.finditer(text or ""):
        raw = match.group(1)
        normalized, confidence, metadata = _normalize(raw)
        if normalized and normalized not in found:
            found[normalized] = EntityResult(
                "phone",
                raw,
                normalized,
                confidence,
                "phone_pattern",
                start_offset=match.start(1),
                end_offset=match.end(1),
                metadata=metadata,
            )
    return list(found.values())
