from __future__ import annotations

import re
from pathlib import Path
from statistics import mean
from typing import Any

_alpr_instance: Any | None = None


def get_alpr() -> Any:
    """Create one FastALPR instance only when the first image is processed."""
    global _alpr_instance
    if _alpr_instance is None:
        from fast_alpr import ALPR

        _alpr_instance = ALPR(
            detector_model="yolo-v9-t-384-license-plate-end2end",
            ocr_model="cct-xs-v2-global-model",
            ocr_device="cpu",
        )
    return _alpr_instance


def normalize_plate(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def recognize_plates(image_path: Path) -> list[dict[str, Any]]:
    """Run one synchronous inference; caller isolates it in a single worker thread."""
    detections: list[dict[str, Any]] = []
    for result in get_alpr().predict(str(image_path)):
        ocr = result.ocr
        if ocr is None or not ocr.text:
            continue
        bbox = result.detection.bounding_box
        confidence = mean(ocr.confidence) if isinstance(ocr.confidence, list) else ocr.confidence
        detections.append(
            {
                "raw_text": ocr.text,
                "normalized_text": normalize_plate(ocr.text),
                "confidence": confidence,
                "bbox_x1": bbox.x1,
                "bbox_y1": bbox.y1,
                "bbox_x2": bbox.x2,
                "bbox_y2": bbox.y2,
            }
        )
    return detections
