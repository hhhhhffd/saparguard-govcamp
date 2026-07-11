from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from contextlib import suppress
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory
from typing import Any

from PIL import Image, ImageOps
from telethon import TelegramClient

from app.config import settings
from app.database.repositories import MediaRepository
from app.database.session import SessionFactory

logger = logging.getLogger(__name__)
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


def save_optimized_image(source_path: Path) -> tuple[dict[str, Any], Path]:
    """Validate, strip metadata, resize and persist a safe JPEG copy by its SHA-256."""
    media_root = settings.media_storage_path.resolve()
    media_root.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as check:
        check.verify()
    temporary_output = media_root / f".{source_path.stem}.jpg"
    with Image.open(source_path) as source:
        image = ImageOps.exif_transpose(source)
        if image.mode != "RGB":
            converted = image.convert("RGB")
            image.close()
            image = converted
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        image.save(temporary_output, "JPEG", quality=82, optimize=True)
        image.close()
    digest = hashlib.sha256()
    with temporary_output.open("rb") as output:
        for chunk in iter(lambda: output.read(1024 * 1024), b""):
            digest.update(chunk)
    sha256 = digest.hexdigest()
    destination = media_root / f"{sha256}.jpg"
    if destination.exists():
        temporary_output.unlink(missing_ok=True)
    else:
        temporary_output.replace(destination)
    return (
        {
            "relative_path": f"media/{destination.name}",
            "mime_type": "image/jpeg",
            "size_bytes": destination.stat().st_size,
            "sha256": sha256,
        },
        destination,
    )


def recognize_plates(image_path: Path) -> list[dict[str, Any]]:
    """Run one synchronous inference; the caller isolates it in a single worker thread."""
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


async def process_one_job(client: TelegramClient) -> bool:
    async with SessionFactory() as session:
        repository = MediaRepository(session)
        job = await repository.claim_next_job()
    if job is None:
        return False
    try:
        entity = await client.get_entity(job.media_file.message.telegram_chat_id)  # type: ignore[attr-defined]
        message = await client.get_messages(entity, ids=job.media_file.message.telegram_message_id)  # type: ignore[attr-defined]
        if message is None or message.media is None:
            raise ValueError("Telegram image is no longer available")
        with TemporaryDirectory(prefix="tg-media-") as directory:
            downloaded = await client.download_media(message, file=directory)
            if not downloaded:
                raise ValueError("Telegram did not return an image file")
            media_values, image_path = await asyncio.to_thread(save_optimized_image, Path(downloaded))
            detections = await asyncio.to_thread(recognize_plates, image_path)
        async with SessionFactory() as session:
            await MediaRepository(session).complete(
                job.id,
                media_file_id=job.media_file_id,
                media_values=media_values,
                detections=detections,
            )
        logger.info("Processed media job %s with %s plate detections", job.id, len(detections))
    except Exception as exc:
        logger.exception("Media job %s failed", job.id)
        async with SessionFactory() as session:
            await MediaRepository(session).fail(
                job,
                str(exc),
                max_attempts=settings.media_job_max_attempts,
                retry_delay_seconds=settings.media_job_retry_delay_seconds,
            )
    return True


async def run_media_worker(client: TelegramClient) -> None:
    """Poll the durable queue without retaining images or queued tasks in memory."""
    async with SessionFactory() as session:
        recovered = await MediaRepository(session).recover_stale_jobs(settings.media_job_stale_timeout_seconds)
    if recovered:
        logger.warning("Returned %s stale media jobs to pending", recovered)
    while True:
        processed = await process_one_job(client)
        if not processed:
            await asyncio.sleep(2)
