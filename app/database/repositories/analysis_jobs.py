from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import ExtractedEntity, MessageAnalysis, MessageAnalysisJob, MessageRoute
from app.processing.text.models import AnalysisResult
from app.processing.profiles.repository import ProfileResolutionRepository


class MessageAnalysisJobRepository:
    """Durable jobs guarded by a lease token against stale worker writes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self, message_id: int, source_text_hash: str, analyzer_version: str, *, force: bool = False
    ) -> bool:
        now = datetime.now(timezone.utc)
        statement = insert(MessageAnalysisJob).values(
            message_id=message_id,
            status="pending",
            attempts=0,
            source_text_hash=source_text_hash,
            analyzer_version=analyzer_version,
            created_at=now,
        )
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            index_elements=[MessageAnalysisJob.message_id],
            set_={
                "status": "pending",
                "attempts": 0,
                "source_text_hash": excluded.source_text_hash,
                "analyzer_version": excluded.analyzer_version,
                "last_error": None,
                "started_at": None,
                "finished_at": None,
                "next_retry_at": None,
                "lease_token": None,
            },
            where=(MessageAnalysisJob.source_text_hash != excluded.source_text_hash)
            | (MessageAnalysisJob.analyzer_version != excluded.analyzer_version)
            if not force
            else None,
        ).returning(MessageAnalysisJob.id)
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    async def recover_stale_jobs(self, timeout_seconds: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        result = await self._session.execute(
            update(MessageAnalysisJob)
            .where(
                MessageAnalysisJob.status == "processing", MessageAnalysisJob.started_at < cutoff
            )
            .values(status="pending", started_at=None, next_retry_at=None, lease_token=None)
        )
        await self._session.commit()
        return result.rowcount or 0

    async def claim_next_job(self) -> MessageAnalysisJob | None:
        lease_token = str(uuid4())
        result = await self._session.execute(
            text(
                "UPDATE message_analysis_jobs SET status = 'processing', attempts = attempts + 1, "
                "started_at = NOW(), last_error = NULL, lease_token = :lease_token WHERE id = ("
                "SELECT id FROM message_analysis_jobs WHERE status = 'pending' "
                "AND (next_retry_at IS NULL OR next_retry_at <= NOW()) ORDER BY created_at ASC "
                "FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING id"
            ),
            {"lease_token": lease_token},
        )
        job_id = result.scalar_one_or_none()
        if job_id is None:
            await self._session.rollback()
            return None
        await self._session.commit()
        result = await self._session.execute(
            select(MessageAnalysisJob)
            .options(selectinload(MessageAnalysisJob.message))
            .where(
                MessageAnalysisJob.id == job_id,
                MessageAnalysisJob.status == "processing",
                MessageAnalysisJob.lease_token == lease_token,
            )
        )
        return result.scalar_one_or_none()

    async def complete(self, job: MessageAnalysisJob, result: AnalysisResult) -> bool:
        now = datetime.now(timezone.utc)
        claimed = await self._claimed_job(job, lock=True)
        if claimed is None:
            await self._session.rollback()
            return False
        statement = insert(MessageAnalysis).values(
            message_id=job.message_id,
            message_type=result.classification.message_type,
            classification_confidence=result.classification.confidence,
            source_text_hash=job.source_text_hash,
            analyzer_version=job.analyzer_version,
            attributes=result.classification.attributes,
            classification_evidence=list(result.classification.evidence),
            processed_at=now,
            created_at=now,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[MessageAnalysis.message_id],
            set_={
                "message_type": statement.excluded.message_type,
                "classification_confidence": statement.excluded.classification_confidence,
                "source_text_hash": statement.excluded.source_text_hash,
                "analyzer_version": statement.excluded.analyzer_version,
                "attributes": statement.excluded.attributes,
                "classification_evidence": statement.excluded.classification_evidence,
                "processed_at": now,
                "updated_at": now,
            },
        ).returning(MessageAnalysis.id)
        analysis_id = (await self._session.execute(statement)).scalar_one()
        await self._session.execute(
            delete(ExtractedEntity).where(ExtractedEntity.analysis_id == analysis_id)
        )
        await self._session.execute(
            delete(MessageRoute).where(MessageRoute.analysis_id == analysis_id)
        )
        if result.entities:
            await self._session.execute(
                insert(ExtractedEntity),
                [
                    {
                        "analysis_id": analysis_id,
                        "entity_type": entity.entity_type,
                        "role": entity.role,
                        "raw_value": entity.raw_value,
                        "normalized_value": entity.normalized_value,
                        "confidence": entity.confidence,
                        "evidence": entity.evidence,
                        "start_offset": entity.start_offset,
                        "end_offset": entity.end_offset,
                        "metadata_": entity.metadata,
                        "created_at": now,
                    }
                    for entity in result.entities
                ],
            )
        if result.routes:
            await self._session.execute(
                insert(MessageRoute),
                [
                    {
                        "analysis_id": analysis_id,
                        "raw_origin": route.raw_origin,
                        "normalized_origin": route.normalized_origin,
                        "raw_destination": route.raw_destination,
                        "normalized_destination": route.normalized_destination,
                        "confidence": route.confidence,
                        "evidence": route.evidence,
                        "created_at": now,
                    }
                    for route in result.routes
                ],
            )
        await self._session.execute(
            update(MessageAnalysisJob)
            .where(
                MessageAnalysisJob.id == job.id, MessageAnalysisJob.lease_token == job.lease_token
            )
            .values(
                status="completed",
                finished_at=now,
                next_retry_at=None,
                last_error=None,
                lease_token=None,
            )
        )
        await ProfileResolutionRepository(self._session).enqueue_for_message(job.message_id)
        await self._session.commit()
        return True

    async def fail(
        self, job: MessageAnalysisJob, error: str, *, max_attempts: int, retry_delay_seconds: int
    ) -> bool:
        if await self._claimed_job(job, lock=False) is None:
            await self._session.rollback()
            return False
        now = datetime.now(timezone.utc)
        terminal = job.attempts >= max_attempts
        await self._session.execute(
            update(MessageAnalysisJob)
            .where(
                MessageAnalysisJob.id == job.id, MessageAnalysisJob.lease_token == job.lease_token
            )
            .values(
                status="failed" if terminal else "pending",
                last_error=error[:1000],
                finished_at=now if terminal else None,
                next_retry_at=None if terminal else now + timedelta(seconds=retry_delay_seconds),
                lease_token=None,
            )
        )
        await self._session.commit()
        return True

    async def _claimed_job(
        self, job: MessageAnalysisJob, *, lock: bool
    ) -> MessageAnalysisJob | None:
        statement = select(MessageAnalysisJob).where(
            MessageAnalysisJob.id == job.id,
            MessageAnalysisJob.status == "processing",
            MessageAnalysisJob.lease_token == job.lease_token,
            MessageAnalysisJob.source_text_hash == job.source_text_hash,
            MessageAnalysisJob.analyzer_version == job.analyzer_version,
        )
        if lock:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)
