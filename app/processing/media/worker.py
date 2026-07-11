from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from telethon import TelegramClient

from app.core.config import settings
from app.core.exceptions import MediaProcessingError
from app.database.repositories import MediaJobRepository
from app.database.session import SessionFactory
from app.processing.media.image_processor import save_optimized_image
from app.processing.media.plate_recognizer import recognize_plates

logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 2


async def process_one_job(client: TelegramClient) -> bool:
    """Claim and process one durable job using the collector's Telegram client."""
    async with SessionFactory() as session:
        job = await MediaJobRepository(session).claim_next_job()
    if job is None:
        return False
    try:
        entity = await client.get_entity(job.media_file.message.telegram_chat_id)
        message = await client.get_messages(entity, ids=job.media_file.message.telegram_message_id)
        if message is None or message.media is None:
            raise MediaProcessingError("Telegram image is no longer available")
        with TemporaryDirectory(prefix="tg-media-") as directory:
            downloaded = await client.download_media(message, file=directory)
            if not downloaded:
                raise MediaProcessingError("Telegram did not return an image file")
            media_values, image_path = await asyncio.to_thread(
                save_optimized_image, Path(downloaded)
            )
            detections = await asyncio.to_thread(recognize_plates, image_path)
        async with SessionFactory() as session:
            await MediaJobRepository(session).complete(
                job.id,
                media_file_id=job.media_file_id,
                media_values=media_values,
                detections=detections,
            )
        logger.info("Processed media job %s with %s plate detections", job.id, len(detections))
    except Exception as exc:
        logger.exception("Media job %s failed", job.id)
        async with SessionFactory() as session:
            await MediaJobRepository(session).fail(
                job,
                str(exc),
                max_attempts=settings.media_job_max_attempts,
                retry_delay_seconds=settings.media_job_retry_delay_seconds,
            )
    return True


async def run_media_worker(client: TelegramClient) -> None:
    """Poll the durable queue; this must run beside its owning TelegramClient."""
    async with SessionFactory() as session:
        recovered = await MediaJobRepository(session).recover_stale_jobs(
            settings.media_job_stale_timeout_seconds
        )
    if recovered:
        logger.warning("Returned %s stale media jobs to pending", recovered)
    while True:
        if not await process_one_job(client):
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
