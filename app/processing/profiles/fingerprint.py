from __future__ import annotations

import hashlib
import json
from typing import Any


def fingerprint(payload: dict[str, Any]) -> str:
    """Return a stable digest for inputs which can alter resolution output."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
