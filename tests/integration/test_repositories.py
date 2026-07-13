from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import (
    ExtractedEntity,
    MediaProcessingJob,
    MessageAnalysis,
    MessageAnalysisJob,
    TelegramChat,
    TelegramMessage,
)
from app.database.repositories import (
    MediaJobRepository,
    MessageAnalysisJobRepository,
    MessageRepository,
)
from app.processing.text.analyzer import analyze_message

pytestmark = pytest.mark.integration

CHAT_ID = -1001234567890


def message_values(message_id: int) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "telegram_chat_id": CHAT_ID,
        "telegram_message_id": message_id,
        "telegram_sender_id": None,
        "text": f"message {message_id}",
        "published_at": now,
        "saved_at": now,
        "is_forwarded": False,
        "forward_source_id": None,
        "forward_source_name": None,
        "media_type": "Photo",
        "edited_at": None,
        "is_deleted": False,
        "deleted_at": None,
    }


async def create_chat(session: AsyncSession) -> None:
    session.add(
        TelegramChat(
            telegram_chat_id=CHAT_ID,
            username=None,
            title="Integration test source",
            chat_type="supergroup",
            is_active=True,
            load_history=True,
            created_at=datetime.now(timezone.utc),
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_repeated_telegram_message_does_not_create_a_duplicate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await create_chat(session)
        repository = MessageRepository(session)
        first = await repository.upsert_message(message_values(1), save_edit=False)
        second = await repository.upsert_message(message_values(1), save_edit=False)

    async with session_factory() as session:
        count = await session.scalar(select(func.count(TelegramMessage.id)))

    assert first.id == second.id
    assert count == 1


@pytest.mark.asyncio
async def test_message_and_media_job_rollback_together(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(RuntimeError, match="force rollback"):
        async with session_factory.begin() as session:
            await create_chat(session)
            message = await MessageRepository(session).upsert_message(
                message_values(1), save_edit=False
            )
            await MediaJobRepository(session).create_pending(
                message.id, source_kind="photo", original_mime_type="image/jpeg"
            )
            raise RuntimeError("force rollback")

    async with session_factory() as session:
        messages = await session.scalar(select(func.count(TelegramMessage.id)))
        jobs = await session.scalar(select(func.count(MediaProcessingJob.id)))

    assert messages == 0
    assert jobs == 0


@pytest.mark.asyncio
async def test_concurrent_claims_lease_different_jobs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await create_chat(session)
        message_repository = MessageRepository(session)
        media_repository = MediaJobRepository(session)
        for message_id in (1, 2):
            message = await message_repository.upsert_message(
                message_values(message_id), save_edit=False
            )
            await media_repository.create_pending(
                message.id, source_kind="photo", original_mime_type="image/jpeg"
            )

    async def claim() -> MediaProcessingJob:
        async with session_factory() as session:
            job = await MediaJobRepository(session).claim_next_job()
            assert job is not None
            return job

    first, second = await asyncio.gather(claim(), claim())

    assert {first.id, second.id} == {1, 2}


@pytest.mark.asyncio
async def test_analysis_completion_replaces_entities_atomically(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await create_chat(session)
        message = await MessageRepository(session).upsert_message(
            message_values(1), save_edit=False
        )
        await MessageAnalysisJobRepository(session).enqueue(message.id, "hash-a", "v1")
    async with session_factory() as session:
        repository = MessageAnalysisJobRepository(session)
        job = await repository.claim_next_job()
        assert job is not None
        assert await repository.complete(
            job, analyze_message("Алматы Бишкек +77020007123 Toyota Camry 70")
        )
    async with session_factory() as session:
        analysis = await session.scalar(select(MessageAnalysis))
        entities = list((await session.scalars(select(ExtractedEntity))).all())
        assert analysis is not None
        assert analysis.classification_evidence
        assert any(entity.metadata_ for entity in entities)


@pytest.mark.asyncio
async def test_requeued_job_rejects_stale_worker_completion(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await create_chat(session)
        message = await MessageRepository(session).upsert_message(
            message_values(1), save_edit=False
        )
        await MessageAnalysisJobRepository(session).enqueue(message.id, "hash-a", "v1")
    async with session_factory() as session:
        stale_job = await MessageAnalysisJobRepository(session).claim_next_job()
        assert stale_job is not None
    async with session_factory.begin() as session:
        assert await MessageAnalysisJobRepository(session).enqueue(
            stale_job.message_id, "hash-b", "v1"
        )
    async with session_factory() as session:
        assert not await MessageAnalysisJobRepository(session).complete(
            stale_job, analyze_message("old")
        )
        job = await session.get(MessageAnalysisJob, stale_job.id)
        assert job is not None and job.status == "pending" and job.source_text_hash == "hash-b"
