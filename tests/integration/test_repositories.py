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
    ProfileOccurrence,
    ProfileRelation,
    ProfileResolutionJob,
    ProfileSharedVehicleObservation,
    ProfileVehicleLinkObservation,
    TransportProfile,
    TelegramChat,
    TelegramMessage,
    Vehicle,
)
from app.database.repositories import (
    MediaJobRepository,
    MessageAnalysisJobRepository,
    MessageRepository,
)
from app.processing.text.analyzer import analyze_message
from app.processing.profiles.repository import ProfileResolutionRepository

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


@pytest.mark.asyncio
async def test_profile_resolution_groups_exact_phone_idempotently(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await create_chat(session)
        for message_id, text in (
            (1, "Такси Алматы Бишкек +77020007123"),
            (2, "Такси Алматы Бишкек Камри +7 702 000 71 23"),
        ):
            values = message_values(message_id)
            values["text"] = text
            message = await MessageRepository(session).upsert_message(values, save_edit=False)
            await MessageAnalysisJobRepository(session).enqueue(
                message.id, f"hash-{message_id}", "v1"
            )
    async with session_factory() as session:
        repository = MessageAnalysisJobRepository(session)
        while job := await repository.claim_next_job():
            assert await repository.complete(job, analyze_message(job.message.text))
    async with session_factory() as session:
        repository = ProfileResolutionRepository(session)
        while job := await repository.claim_next_job():
            assert await repository.resolve(job) == "completed"
    async with session_factory() as session:
        assert await session.scalar(select(func.count(TransportProfile.id))) == 1
        assert await session.scalar(select(func.count(ProfileOccurrence.id))) == 2
        job = await session.scalar(select(ProfileResolutionJob).limit(1))
        assert job is not None
        assert not await ProfileResolutionRepository(session).enqueue_for_message(job.message_id)


@pytest.mark.asyncio
async def test_shared_vehicle_is_aggregated_across_messages(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    observed_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    async with session_factory.begin() as session:
        first = TransportProfile(
            profile_kind="phone",
            canonical_label="A",
            status="active",
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            occurrence_count=0,
            active_occurrence_count=0,
            resolver_version="test",
            created_at=observed_at,
            updated_at=observed_at,
        )
        second = TransportProfile(
            profile_kind="phone",
            canonical_label="B",
            status="active",
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            occurrence_count=0,
            active_occurrence_count=0,
            resolver_version="test",
            created_at=observed_at,
            updated_at=observed_at,
        )
        vehicle = Vehicle(
            identity_kind="plate",
            normalized_plate="123ABC01",
            profile_signature_key=None,
            make=None,
            model=None,
            generation=None,
            year=None,
            canonical_label="123ABC01",
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            observation_count=0,
            created_at=observed_at,
            updated_at=observed_at,
        )
        session.add_all((first, second, vehicle))
        await session.flush()
        await create_chat(session)
        messages = [
            await MessageRepository(session).upsert_message(
                message_values(message_id), save_edit=False
            )
            for message_id in (1, 2)
        ]
        session.add_all(
            (
                ProfileVehicleLinkObservation(
                    profile_id=first.id,
                    vehicle_id=vehicle.id,
                    message_id=messages[0].id,
                    confidence=1.0,
                    evidence={},
                    observed_at=observed_at,
                    created_at=observed_at,
                ),
                ProfileVehicleLinkObservation(
                    profile_id=second.id,
                    vehicle_id=vehicle.id,
                    message_id=messages[1].id,
                    confidence=1.0,
                    evidence={},
                    observed_at=observed_at,
                    created_at=observed_at,
                ),
            )
        )
        vehicle_id = vehicle.id
        profile_ids = {first.id, second.id}
    async with session_factory.begin() as session:
        repository = ProfileResolutionRepository(session)
        await repository._refresh_shared_vehicle_observations({vehicle_id})
        await repository._refresh_relations(profile_ids)
    async with session_factory() as session:
        source = await session.scalar(select(ProfileSharedVehicleObservation))
        relation = await session.scalar(
            select(ProfileRelation).where(ProfileRelation.relation_type == "shared_vehicle")
        )
        assert source is not None and source.vehicle_id == vehicle_id
        assert relation is not None
        assert relation.evidence == {"vehicle_ids": [vehicle_id], "source_count": 1}
