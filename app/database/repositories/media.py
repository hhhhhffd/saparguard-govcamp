from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import MediaFile, MediaProcessingJob, PlateDetection


class MediaRepository:
    """Persistent PostgreSQL-backed queue and metadata for Telegram images."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_pending(self, message_id: int, *, source_kind: str, original_mime_type: str | None) -> None:
        now = datetime.now(timezone.utc)
        media_statement = insert(MediaFile).values(
            message_id=message_id,
            source_kind=source_kind,
            original_mime_type=original_mime_type,
            processing_status="pending",
            created_at=now,
        ).on_conflict_do_nothing(index_elements=[MediaFile.message_id]).returning(MediaFile.id)
        media_file_id = (await self._session.execute(media_statement)).scalar_one_or_none()
        if media_file_id is not None:
            await self._session.execute(
                insert(MediaProcessingJob).values(
                    message_id=message_id,
                    media_file_id=media_file_id,
                    status="pending",
                    attempts=0,
                    created_at=now,
                )
            )
        await self._session.commit()

    async def recover_stale_jobs(self, timeout_seconds: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        result = await self._session.execute(
            update(MediaProcessingJob)
            .where(MediaProcessingJob.status == "processing", MediaProcessingJob.started_at < cutoff)
            .values(status="pending", next_retry_at=None, started_at=None)
        )
        await self._session.commit()
        return result.rowcount or 0

    async def claim_next_job(self) -> MediaProcessingJob | None:
        result = await self._session.execute(
            text(
                """
                UPDATE media_processing_jobs
                SET status = 'processing', attempts = attempts + 1, started_at = NOW(), last_error = NULL
                WHERE id = (
                    SELECT id
                    FROM media_processing_jobs
                    WHERE status = 'pending'
                      AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                    ORDER BY created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING id
                """
            )
        )
        job_id = result.scalar_one_or_none()
        if job_id is None:
            await self._session.rollback()
            return None
        await self._session.commit()
        result = await self._session.execute(
            select(MediaProcessingJob)
            .options(selectinload(MediaProcessingJob.media_file).selectinload(MediaFile.message))
            .where(MediaProcessingJob.id == job_id)
        )
        return result.scalar_one()

    async def complete(
        self,
        job_id: int,
        *,
        media_file_id: int,
        media_values: dict[str, Any],
        detections: list[dict[str, Any]],
    ) -> None:
        now = datetime.now(timezone.utc)
        status = "completed" if detections else "no_plate_found"
        await self._session.execute(
            update(MediaFile)
            .where(MediaFile.id == media_file_id)
            .values(**media_values, processing_status=status, updated_at=now)
        )
        await self._session.execute(delete(PlateDetection).where(PlateDetection.media_file_id == media_file_id))
        if detections:
            await self._session.execute(
                insert(PlateDetection),
                [{**detection, "media_file_id": media_file_id, "created_at": now} for detection in detections],
            )
        await self._session.execute(
            update(MediaProcessingJob)
            .where(MediaProcessingJob.id == job_id)
            .values(status=status, finished_at=now, next_retry_at=None, last_error=None)
        )
        await self._session.commit()

    async def fail(self, job: MediaProcessingJob, error: str, *, max_attempts: int, retry_delay_seconds: int) -> None:
        now = datetime.now(timezone.utc)
        terminal = job.attempts >= max_attempts
        status = "failed" if terminal else "pending"
        next_retry_at = None if terminal else now + timedelta(seconds=retry_delay_seconds)
        await self._session.execute(
            update(MediaFile)
            .where(MediaFile.id == job.media_file_id)
            .values(processing_status=status, updated_at=now)
        )
        await self._session.execute(
            update(MediaProcessingJob)
            .where(MediaProcessingJob.id == job.id)
            .values(status=status, last_error=error[:1000], finished_at=now if terminal else None, next_retry_at=next_retry_at)
        )
        await self._session.commit()

    async def get_file(self, media_file_id: int) -> MediaFile | None:
        return await self._session.get(MediaFile, media_file_id)
