from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.database.models import (
    ExtractedEntity,
    MediaFile,
    MessageAnalysis,
    PlateDetection,
    ProfileIdentifier,
    ProfileOccurrence,
    ProfileRelation,
    ProfileResolutionConflict,
    ProfileResolutionJob,
    ProfileVehicleLink,
    TelegramMessage,
    TransportProfile,
    Vehicle,
    VehicleObservation,
)
from app.processing.profiles.fingerprint import fingerprint

PROVIDER_TYPES = {"driver_offer", "parcel_offer"}


class ProfileResolutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue_for_message(self, message_id: int, *, force: bool = False) -> bool:
        payload = await self._fingerprint_payload(message_id)
        if payload is None:
            return False
        digest = fingerprint(payload)
        now = datetime.now(timezone.utc)
        statement = insert(ProfileResolutionJob).values(
            message_id=message_id,
            status="pending",
            attempts=0,
            source_fingerprint=digest,
            resolver_version=settings.profile_resolver_version,
            created_at=now,
        )
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            index_elements=[ProfileResolutionJob.message_id],
            set_={
                "status": "pending",
                "attempts": 0,
                "source_fingerprint": excluded.source_fingerprint,
                "resolver_version": excluded.resolver_version,
                "lease_token": None,
                "last_error": None,
                "started_at": None,
                "finished_at": None,
                "next_retry_at": None,
            },
            where=None
            if force
            else (
                (ProfileResolutionJob.source_fingerprint != excluded.source_fingerprint)
                | (ProfileResolutionJob.resolver_version != excluded.resolver_version)
            ),
        ).returning(ProfileResolutionJob.id)
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    async def _fingerprint_payload(self, message_id: int) -> dict[str, object] | None:
        message = await self._load_message(message_id)
        if message is None:
            return None
        analysis = message.analysis
        entities = analysis.entities if analysis else []
        routes = analysis.routes if analysis else []
        plates = [plate for media in message.media_files for plate in media.plate_detections]
        return {
            "message_id": message.id,
            "is_deleted": message.is_deleted,
            "sender_id": message.telegram_sender_id,
            "analysis_hash": analysis.source_text_hash if analysis else None,
            "analyzer_version": analysis.analyzer_version if analysis else None,
            "message_type": analysis.message_type if analysis else None,
            "entities": sorted(
                (e.entity_type, e.normalized_value, e.confidence, e.metadata_) for e in entities
            ),
            "routes": sorted(
                (r.normalized_origin, r.normalized_destination, r.confidence) for r in routes
            ),
            "plates": sorted((p.id, p.normalized_text, p.confidence) for p in plates),
            "resolver_version": settings.profile_resolver_version,
        }

    async def recover_stale_jobs(self, timeout_seconds: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        result = await self._session.execute(
            update(ProfileResolutionJob)
            .where(
                ProfileResolutionJob.status == "processing",
                ProfileResolutionJob.started_at < cutoff,
            )
            .values(status="pending", started_at=None, lease_token=None, next_retry_at=None)
        )
        await self._session.commit()
        return result.rowcount or 0

    async def claim_next_job(self) -> ProfileResolutionJob | None:
        token = str(uuid4())
        result = await self._session.execute(
            text(
                "UPDATE profile_resolution_jobs SET status = 'processing', attempts = attempts + 1, started_at = NOW(), last_error = NULL, lease_token = :token WHERE id = (SELECT id FROM profile_resolution_jobs WHERE status = 'pending' AND (next_retry_at IS NULL OR next_retry_at <= NOW()) ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING id"
            ),
            {"token": token},
        )
        job_id = result.scalar_one_or_none()
        if job_id is None:
            await self._session.rollback()
            return None
        await self._session.commit()
        return await self._session.scalar(
            select(ProfileResolutionJob).where(
                ProfileResolutionJob.id == job_id, ProfileResolutionJob.lease_token == token
            )
        )

    async def resolve(self, job: ProfileResolutionJob) -> str:
        claimed = await self._session.scalar(
            select(ProfileResolutionJob)
            .where(
                ProfileResolutionJob.id == job.id,
                ProfileResolutionJob.status == "processing",
                ProfileResolutionJob.lease_token == job.lease_token,
                ProfileResolutionJob.source_fingerprint == job.source_fingerprint,
            )
            .with_for_update()
        )
        if claimed is None:
            await self._session.rollback()
            return "stale"
        message = await self._load_message(job.message_id)
        if message is None:
            await self._complete(job)
            await self._session.commit()
            return "completed"
        if not self._analysis_current(message):
            await self._session.execute(
                update(ProfileResolutionJob)
                .where(
                    ProfileResolutionJob.id == job.id,
                    ProfileResolutionJob.lease_token == job.lease_token,
                )
                .values(
                    status="waiting",
                    lease_token=None,
                    next_retry_at=datetime.now(timezone.utc)
                    + timedelta(seconds=settings.profile_job_retry_delay_seconds),
                )
            )
            await self._session.commit()
            return "waiting"
        current_fingerprint = fingerprint((await self._fingerprint_payload(job.message_id)) or {})
        if current_fingerprint != job.source_fingerprint:
            await self._session.rollback()
            return "stale"
        old_profile_ids = list(
            (
                await self._session.scalars(
                    select(ProfileOccurrence.profile_id).where(
                        ProfileOccurrence.message_id == message.id
                    )
                )
            ).all()
        )
        old_vehicle_ids = list(
            (
                await self._session.scalars(
                    select(VehicleObservation.vehicle_id).where(
                        VehicleObservation.message_id == message.id
                    )
                )
            ).all()
        )
        await self._session.execute(
            delete(ProfileOccurrence).where(ProfileOccurrence.message_id == message.id)
        )
        await self._session.execute(
            delete(VehicleObservation).where(VehicleObservation.message_id == message.id)
        )
        await self._session.execute(
            delete(ProfileResolutionConflict).where(
                ProfileResolutionConflict.message_id == message.id
            )
        )
        analysis = message.analysis
        phones = [entity for entity in analysis.entities if entity.entity_type == "phone"]
        profiles: list[TransportProfile] = []
        if analysis.message_type in PROVIDER_TYPES:
            for phone in phones:
                profiles.append(await self._phone_profile(phone, message))
            if (
                not profiles
                and message.telegram_sender_id is not None
                and not await self._sender_is_relay(message.telegram_sender_id)
            ):
                profiles.append(await self._telegram_profile(message))
        profiles = list({profile.id: profile for profile in profiles}.values())
        now = datetime.now(timezone.utc)
        for profile in profiles:
            method = "exact_phone" if phones else "telegram_user_id"
            await self._session.execute(
                insert(ProfileOccurrence).values(
                    profile_id=profile.id,
                    message_id=message.id,
                    match_method=method,
                    confidence=1.0,
                    evidence={
                        "entity_id": next((phone.id for phone in phones), None),
                        "classification": analysis.message_type,
                    },
                    source_deleted=message.is_deleted,
                    first_seen_at=now,
                    last_resolved_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        if len(profiles) > 1:
            for index, left in enumerate(profiles):
                for right in profiles[index + 1 :]:
                    await self._relation(
                        left.id, right.id, "co_occurring_contact", {"message_id": message.id}
                    )
        if phones and message.telegram_sender_id is not None:
            telegram = await self._existing_telegram_profile(message.telegram_sender_id)
            if telegram:
                for profile in profiles:
                    if profile.id != telegram.id:
                        await self._relation(
                            telegram.id, profile.id, "shared_sender", {"message_id": message.id}
                        )
        await self._resolve_vehicles(message, profiles)
        affected_profiles = set(old_profile_ids) | {profile.id for profile in profiles}
        affected_vehicles = set(old_vehicle_ids) | set(
            (
                await self._session.scalars(
                    select(VehicleObservation.vehicle_id).where(
                        VehicleObservation.message_id == message.id
                    )
                )
            ).all()
        )
        for profile_id in affected_profiles:
            await self._refresh_profile(profile_id)
        for vehicle_id in affected_vehicles:
            await self._refresh_vehicle(vehicle_id)
        await self._refresh_links_and_shared_vehicle(message.id, affected_profiles)
        await self._complete(job)
        await self._session.commit()
        return "completed"

    async def _load_message(self, message_id: int) -> TelegramMessage | None:
        return await self._session.scalar(
            select(TelegramMessage)
            .options(
                selectinload(TelegramMessage.sender),
                selectinload(TelegramMessage.analysis).selectinload(MessageAnalysis.entities),
                selectinload(TelegramMessage.analysis).selectinload(MessageAnalysis.routes),
                selectinload(TelegramMessage.analysis_job),
                selectinload(TelegramMessage.media_files).selectinload(MediaFile.plate_detections),
            )
            .where(TelegramMessage.id == message_id)
        )

    @staticmethod
    def _analysis_current(message: TelegramMessage) -> bool:
        return bool(
            message.analysis
            and message.analysis_job
            and message.analysis_job.status == "completed"
            and message.analysis.source_text_hash == message.analysis_job.source_text_hash
            and message.analysis.analyzer_version == message.analysis_job.analyzer_version
        )

    async def _phone_profile(
        self, entity: ExtractedEntity, message: TelegramMessage
    ) -> TransportProfile:
        profile = await self._session.scalar(
            select(TransportProfile)
            .join(ProfileIdentifier)
            .where(
                ProfileIdentifier.identifier_type == "phone",
                ProfileIdentifier.identifier_role == "anchor",
                ProfileIdentifier.normalized_value == entity.normalized_value,
            )
            .with_for_update()
        )
        now = datetime.now(timezone.utc)
        if profile is None:
            profile = TransportProfile(
                profile_kind="phone",
                canonical_label=f"Перевозчик {entity.normalized_value}",
                status="active",
                first_seen_at=now,
                last_seen_at=now,
                occurrence_count=0,
                active_occurrence_count=0,
                resolver_version=settings.profile_resolver_version,
                created_at=now,
                updated_at=now,
            )
            self._session.add(profile)
            await self._session.flush()
            self._session.add(
                ProfileIdentifier(
                    profile_id=profile.id,
                    identifier_type="phone",
                    identifier_role="anchor",
                    raw_value=entity.raw_value,
                    normalized_value=entity.normalized_value,
                    confidence=entity.confidence,
                    source_message_id=message.id,
                    first_seen_at=now,
                    last_seen_at=now,
                    occurrence_count=1,
                    created_at=now,
                    updated_at=now,
                )
            )
        return profile

    async def _existing_telegram_profile(self, sender_id: int) -> TransportProfile | None:
        return await self._session.scalar(
            select(TransportProfile)
            .join(ProfileIdentifier)
            .where(
                ProfileIdentifier.identifier_type == "telegram_user_id",
                ProfileIdentifier.identifier_role == "anchor",
                ProfileIdentifier.normalized_value == str(sender_id),
            )
        )

    async def _telegram_profile(self, message: TelegramMessage) -> TransportProfile:
        existing = await self._existing_telegram_profile(message.telegram_sender_id or 0)
        now = datetime.now(timezone.utc)
        if existing:
            return existing
        profile = TransportProfile(
            profile_kind="telegram",
            canonical_label=f"Telegram-профиль {message.telegram_sender_id}",
            status="active",
            first_seen_at=now,
            last_seen_at=now,
            occurrence_count=0,
            active_occurrence_count=0,
            resolver_version=settings.profile_resolver_version,
            created_at=now,
            updated_at=now,
        )
        self._session.add(profile)
        await self._session.flush()
        self._session.add(
            ProfileIdentifier(
                profile_id=profile.id,
                identifier_type="telegram_user_id",
                identifier_role="anchor",
                raw_value=str(message.telegram_sender_id),
                normalized_value=str(message.telegram_sender_id),
                confidence=1.0,
                source_message_id=message.id,
                first_seen_at=now,
                last_seen_at=now,
                occurrence_count=1,
                created_at=now,
                updated_at=now,
            )
        )
        if message.sender and message.sender.username:
            self._session.add(
                ProfileIdentifier(
                    profile_id=profile.id,
                    identifier_type="telegram_username",
                    identifier_role="observed",
                    raw_value=message.sender.username,
                    normalized_value=message.sender.username.casefold(),
                    confidence=1.0,
                    source_message_id=message.id,
                    first_seen_at=now,
                    last_seen_at=now,
                    occurrence_count=1,
                    created_at=now,
                    updated_at=now,
                )
            )
        return profile

    async def _sender_is_relay(self, sender_id: int) -> bool:
        sender = await self._session.scalar(
            select(TelegramMessage)
            .options(selectinload(TelegramMessage.sender))
            .where(TelegramMessage.telegram_sender_id == sender_id)
            .limit(1)
        )
        if (
            sender
            and sender.sender
            and sender.sender.username
            and sender.sender.username.casefold().endswith("bot")
        ):
            return True
        phone_count = await self._session.scalar(
            select(func.count(func.distinct(ExtractedEntity.normalized_value)))
            .join(MessageAnalysis)
            .join(TelegramMessage)
            .where(
                TelegramMessage.telegram_sender_id == sender_id,
                ExtractedEntity.entity_type == "phone",
            )
        )
        return (phone_count or 0) >= settings.profile_sender_relay_distinct_phone_limit

    async def _relation(
        self, profile_a: int, profile_b: int, kind: str, evidence: dict[str, object]
    ) -> None:
        if profile_a == profile_b:
            return
        left, right = sorted((profile_a, profile_b))
        now = datetime.now(timezone.utc)
        stmt = insert(ProfileRelation).values(
            left_profile_id=left,
            right_profile_id=right,
            relation_type=kind,
            confidence=1.0,
            first_seen_at=now,
            last_seen_at=now,
            occurrence_count=1,
            evidence=evidence,
            created_at=now,
            updated_at=now,
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=["left_profile_id", "right_profile_id", "relation_type"],
                set_={
                    "last_seen_at": now,
                    "occurrence_count": ProfileRelation.occurrence_count + 1,
                    "evidence": evidence,
                    "updated_at": now,
                },
            )
        )

    async def _resolve_vehicles(
        self, message: TelegramMessage, profiles: list[TransportProfile]
    ) -> None:
        entities = [
            entity for entity in message.analysis.entities if entity.entity_type == "vehicle"
        ]
        plates = [plate for media in message.media_files for plate in media.plate_detections]
        high_plates = [
            plate
            for plate in plates
            if (plate.confidence or 0) >= settings.profile_plate_min_confidence
        ]
        if len(entities) > 1 and len(high_plates) > 1:
            now = datetime.now(timezone.utc)
            self._session.add(
                ProfileResolutionConflict(
                    message_id=message.id,
                    conflict_type="multiple_vehicles_multiple_plates",
                    status="open",
                    details={"vehicle_count": len(entities), "plate_count": len(high_plates)},
                    created_at=now,
                    updated_at=now,
                )
            )
        if len(entities) == 1 and len(high_plates) == 1:
            vehicle = await self._plate_vehicle(high_plates[0], entities[0].metadata_)
            await self._observe_vehicle(
                vehicle, message, profiles, "text", entities[0].id, None, entities[0].confidence
            )
            await self._observe_vehicle(
                vehicle,
                message,
                profiles,
                "alpr",
                None,
                high_plates[0].id,
                high_plates[0].confidence or 0,
            )
        else:
            for plate in high_plates:
                vehicle = await self._plate_vehicle(plate, {})
                await self._observe_vehicle(
                    vehicle, message, profiles, "alpr", None, plate.id, plate.confidence or 0
                )
            for entity in entities:
                for profile in profiles:
                    vehicle = await self._signature_vehicle(profile.id, entity.metadata_)
                    await self._observe_vehicle(
                        vehicle, message, [profile], "text", entity.id, None, entity.confidence
                    )

    async def _plate_vehicle(self, plate: PlateDetection, metadata: dict[str, object]) -> Vehicle:
        vehicle = await self._session.scalar(
            select(Vehicle)
            .where(Vehicle.normalized_plate == plate.normalized_text)
            .with_for_update()
        )
        if vehicle:
            return vehicle
        now = datetime.now(timezone.utc)
        vehicle = Vehicle(
            identity_kind="plate",
            normalized_plate=plate.normalized_text,
            make=metadata.get("make"),
            model=metadata.get("model"),
            generation=metadata.get("generation"),
            year=metadata.get("year"),
            canonical_label=plate.normalized_text,
            first_seen_at=now,
            last_seen_at=now,
            observation_count=0,
            created_at=now,
            updated_at=now,
        )
        self._session.add(vehicle)
        await self._session.flush()
        return vehicle

    async def _signature_vehicle(self, profile_id: int, metadata: dict[str, object]) -> Vehicle:
        signature = {key: metadata.get(key) for key in ("make", "model", "generation", "year")}
        existing = await self._session.scalar(
            select(Vehicle)
            .join(VehicleObservation)
            .where(
                Vehicle.normalized_plate.is_(None),
                VehicleObservation.profile_id == profile_id,
                Vehicle.make == signature["make"],
                Vehicle.model == signature["model"],
                Vehicle.generation == signature["generation"],
                Vehicle.year == signature["year"],
            )
        )
        if existing:
            return existing
        parts = [
            str(signature[key])
            for key in ("make", "model", "generation", "year")
            if signature[key] is not None
        ]
        now = datetime.now(timezone.utc)
        vehicle = Vehicle(
            identity_kind="profile_signature",
            normalized_plate=None,
            **signature,
            canonical_label=" ".join(parts) or "Неопределённый автомобиль",
            first_seen_at=now,
            last_seen_at=now,
            observation_count=0,
            created_at=now,
            updated_at=now,
        )
        self._session.add(vehicle)
        await self._session.flush()
        return vehicle

    async def _observe_vehicle(
        self,
        vehicle: Vehicle,
        message: TelegramMessage,
        profiles: list[TransportProfile],
        source_type: str,
        entity_id: int | None,
        plate_id: int | None,
        confidence: float,
    ) -> None:
        now = datetime.now(timezone.utc)
        for profile in profiles or [None]:
            self._session.add(
                VehicleObservation(
                    vehicle_id=vehicle.id,
                    message_id=message.id,
                    profile_id=profile.id if profile else None,
                    source_type=source_type,
                    extracted_entity_id=entity_id,
                    plate_detection_id=plate_id,
                    confidence=confidence,
                    evidence={"message_id": message.id},
                    created_at=now,
                    updated_at=now,
                )
            )

    async def _refresh_profile(self, profile_id: int) -> None:
        rows = await self._session.execute(
            select(
                func.count(ProfileOccurrence.id),
                func.count(ProfileOccurrence.id).filter(
                    ProfileOccurrence.source_deleted.is_(False)
                ),
                func.min(ProfileOccurrence.first_seen_at),
                func.max(ProfileOccurrence.last_resolved_at),
            ).where(ProfileOccurrence.profile_id == profile_id)
        )
        total, active, first, last = rows.one()
        if total:
            await self._session.execute(
                update(TransportProfile)
                .where(TransportProfile.id == profile_id)
                .values(
                    occurrence_count=total,
                    active_occurrence_count=active,
                    first_seen_at=first,
                    last_seen_at=last,
                    updated_at=datetime.now(timezone.utc),
                )
            )

    async def _refresh_vehicle(self, vehicle_id: int) -> None:
        total, first, last = (
            await self._session.execute(
                select(
                    func.count(VehicleObservation.id),
                    func.min(VehicleObservation.created_at),
                    func.max(VehicleObservation.created_at),
                ).where(VehicleObservation.vehicle_id == vehicle_id)
            )
        ).one()
        if total:
            await self._session.execute(
                update(Vehicle)
                .where(Vehicle.id == vehicle_id)
                .values(
                    observation_count=total,
                    first_seen_at=first,
                    last_seen_at=last,
                    updated_at=datetime.now(timezone.utc),
                )
            )

    async def _refresh_links_and_shared_vehicle(
        self, message_id: int, profile_ids: set[int]
    ) -> None:
        now = datetime.now(timezone.utc)
        rows = await self._session.execute(
            select(VehicleObservation.profile_id, VehicleObservation.vehicle_id).where(
                VehicleObservation.message_id == message_id,
                VehicleObservation.profile_id.is_not(None),
            )
        )
        for profile_id, vehicle_id in rows:
            await self._session.execute(
                insert(ProfileVehicleLink)
                .values(
                    profile_id=profile_id,
                    vehicle_id=vehicle_id,
                    first_seen_at=now,
                    last_seen_at=now,
                    occurrence_count=1,
                    confidence=1.0,
                    evidence={"message_id": message_id},
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["profile_id", "vehicle_id"],
                    set_={
                        "last_seen_at": now,
                        "occurrence_count": ProfileVehicleLink.occurrence_count + 1,
                        "updated_at": now,
                    },
                )
            )
            linked = list(
                (
                    await self._session.scalars(
                        select(ProfileVehicleLink.profile_id).where(
                            ProfileVehicleLink.vehicle_id == vehicle_id
                        )
                    )
                ).all()
            )
            for related in linked:
                if related != profile_id:
                    await self._relation(
                        profile_id, related, "shared_vehicle", {"vehicle_id": vehicle_id}
                    )

    async def _complete(self, job: ProfileResolutionJob) -> None:
        result = await self._session.execute(
            update(ProfileResolutionJob)
            .where(
                ProfileResolutionJob.id == job.id,
                ProfileResolutionJob.status == "processing",
                ProfileResolutionJob.lease_token == job.lease_token,
                ProfileResolutionJob.source_fingerprint == job.source_fingerprint,
            )
            .values(
                status="completed",
                finished_at=datetime.now(timezone.utc),
                next_retry_at=None,
                last_error=None,
                lease_token=None,
            )
        )
        if not result.rowcount:
            raise RuntimeError("Profile resolution lease expired")

    async def fail(self, job: ProfileResolutionJob, error: str) -> bool:
        terminal = job.attempts >= settings.profile_job_max_attempts
        now = datetime.now(timezone.utc)
        result = await self._session.execute(
            update(ProfileResolutionJob)
            .where(
                ProfileResolutionJob.id == job.id,
                ProfileResolutionJob.status == "processing",
                ProfileResolutionJob.lease_token == job.lease_token,
            )
            .values(
                status="failed" if terminal else "pending",
                last_error=error[:1000],
                finished_at=now if terminal else None,
                next_retry_at=None
                if terminal
                else now + timedelta(seconds=settings.profile_job_retry_delay_seconds),
                lease_token=None,
            )
        )
        await self._session.commit()
        return bool(result.rowcount)
