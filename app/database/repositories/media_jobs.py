from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import MediaJobStatus, MediaProcessingStatus
from app.database.models import MediaFile, MediaProcessingJob, PlateDetection
from app.processing.profiles.repository import ProfileResolutionRepository


class MediaJobRepository:
    """Persistent queue operations with explicit atomic transaction contracts.

    Claim, recovery and terminal transitions commit atomically because each is executed by
    an independent worker session. `create_pending` deliberately does not commit: the
    collector stores its message and its first job in one service-owned transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_pending(
        self, message_id: int, *, source_kind: str, original_mime_type: str | None
    ) -> None:
        now = datetime.now(timezone.utc)
        media_statement = (
            insert(MediaFile)
            .values(
                message_id=message_id,
                source_kind=source_kind,
                original_mime_type=original_mime_type,
                processing_status=MediaProcessingStatus.PENDING,
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=[MediaFile.message_id])
            .returning(MediaFile.id)
        )
        media_file_id = (await self._session.execute(media_statement)).scalar_one_or_none()
        if media_file_id is not None:
            await self._session.execute(
                insert(MediaProcessingJob).values(
                    message_id=message_id,
                    media_file_id=media_file_id,
                    status=MediaJobStatus.PENDING,
                    attempts=0,
                    created_at=now,
                )
            )

    async def recover_stale_jobs(self, timeout_seconds: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        result = await self._session.execute(
            update(MediaProcessingJob)
            .where(
                MediaProcessingJob.status == MediaJobStatus.PROCESSING,
                MediaProcessingJob.started_at < cutoff,
            )
            .values(status=MediaJobStatus.PENDING, next_retry_at=None, started_at=None)
        )
        await self._session.execute(
            update(MediaFile)
            .where(
                MediaFile.id.in_(
                    select(MediaProcessingJob.media_file_id).where(
                        MediaProcessingJob.status == MediaJobStatus.PENDING
                    )
                )
            )
            .values(
                processing_status=MediaProcessingStatus.PENDING,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self._session.commit()
        return result.rowcount or 0

    async def claim_next_job(self) -> MediaProcessingJob | None:
        """Atomically lease one pending job with PostgreSQL `FOR UPDATE SKIP LOCKED`."""
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
                RETURNING id, media_file_id
                """
            )
        )
        row = result.one_or_none()
        if row is None:
            await self._session.rollback()
            return None
        await self._session.execute(
            update(MediaFile)
            .where(MediaFile.id == row.media_file_id)
            .values(
                processing_status=MediaProcessingStatus.PROCESSING,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self._session.commit()
        result = await self._session.execute(
            select(MediaProcessingJob)
            .options(selectinload(MediaProcessingJob.media_file).selectinload(MediaFile.message))
            .where(MediaProcessingJob.id == row.id)
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
        processing_status = (
            MediaProcessingStatus.COMPLETED if detections else MediaProcessingStatus.NO_PLATE_FOUND
        )
        await self._session.execute(
            update(MediaFile)
            .where(MediaFile.id == media_file_id)
            .values(**media_values, processing_status=processing_status, updated_at=now)
        )
        await self._session.execute(
            delete(PlateDetection).where(PlateDetection.media_file_id == media_file_id)
        )
        if detections:
            await self._session.execute(
                insert(PlateDetection),
                [
                    {**detection, "media_file_id": media_file_id, "created_at": now}
                    for detection in detections
                ],
            )
        await self._session.execute(
            update(MediaProcessingJob)
            .where(MediaProcessingJob.id == job_id)
            .values(
                status=MediaJobStatus.COMPLETED,
                finished_at=now,
                next_retry_at=None,
                last_error=None,
            )
        )
        await ProfileResolutionRepository(self._session).enqueue_for_message(
            (
                await self._session.scalar(
                    select(MediaFile.message_id).where(MediaFile.id == media_file_id)
                )
            )
        )
        await self._session.commit()

    async def fail(
        self,
        job: MediaProcessingJob,
        error: str,
        *,
        max_attempts: int,
        retry_delay_seconds: int,
    ) -> None:
        now = datetime.now(timezone.utc)
        terminal = job.attempts >= max_attempts
        job_status = MediaJobStatus.FAILED if terminal else MediaJobStatus.PENDING
        processing_status = (
            MediaProcessingStatus.FAILED if terminal else MediaProcessingStatus.PENDING
        )
        next_retry_at = None if terminal else now + timedelta(seconds=retry_delay_seconds)
        await self._session.execute(
            update(MediaFile)
            .where(MediaFile.id == job.media_file_id)
            .values(processing_status=processing_status, updated_at=now)
        )
        await self._session.execute(
            update(MediaProcessingJob)
            .where(MediaProcessingJob.id == job.id)
            .values(
                status=job_status,
                last_error=error[:1000],
                finished_at=now if terminal else None,
                next_retry_at=next_retry_at,
            )
        )
        await self._session.commit()

    async def get_file(self, media_file_id: int) -> MediaFile | None:
        return await self._session.get(MediaFile, media_file_id)
