from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
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
    ProfileRelationObservation,
    ProfileSharedVehicleObservation,
    ProfileResolutionConflict,
    ProfileResolutionJob,
    ProfileVehicleLink,
    ProfileVehicleLinkObservation,
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
                "UPDATE profile_resolution_jobs SET status = 'processing', attempts = attempts + 1, started_at = NOW(), last_error = NULL, lease_token = :token WHERE id = (SELECT id FROM profile_resolution_jobs WHERE status IN ('pending', 'waiting') AND (next_retry_at IS NULL OR next_retry_at <= NOW()) ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING id"
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
        if message.is_deleted:
            await self._session.execute(
                update(ProfileOccurrence)
                .where(ProfileOccurrence.message_id == message.id)
                .values(source_deleted=True, updated_at=datetime.now(timezone.utc))
            )
        else:
            await self._session.execute(
                delete(ProfileOccurrence).where(ProfileOccurrence.message_id == message.id)
            )
        await self._session.execute(
            delete(VehicleObservation).where(VehicleObservation.message_id == message.id)
        )
        await self._session.execute(
            delete(ProfileRelationObservation).where(
                ProfileRelationObservation.message_id == message.id
            )
        )
        await self._session.execute(
            delete(ProfileVehicleLinkObservation).where(
                ProfileVehicleLinkObservation.message_id == message.id
            )
        )
        analysis = message.analysis
        phones = [entity for entity in analysis.entities if entity.entity_type == "phone"]
        profiles: list[TransportProfile] = []
        is_provider = not message.is_deleted and analysis.message_type in PROVIDER_TYPES
        profile_phone_entities: dict[int, ExtractedEntity] = {}
        if is_provider:
            for phone in phones:
                profile = await self._phone_profile(phone, message)
                profiles.append(profile)
                profile_phone_entities[profile.id] = phone
            if (
                not profiles
                and message.telegram_sender_id is not None
                and not await self._sender_is_relay(message.telegram_sender_id)
            ):
                profiles.append(await self._telegram_profile(message))
        profiles = list({profile.id: profile for profile in profiles}.values())
        now = datetime.now(timezone.utc)
        for profile in profiles:
            phone = profile_phone_entities.get(profile.id)
            method = "exact_phone" if phone else "telegram_user_id"
            await self._session.execute(
                insert(ProfileOccurrence).values(
                    profile_id=profile.id,
                    message_id=message.id,
                    match_method=method,
                    confidence=1.0,
                    evidence={
                        "matched_phone": phone.normalized_value if phone else None,
                        "entity_id": phone.id if phone else None,
                        "classification": analysis.message_type,
                    },
                    source_deleted=message.is_deleted,
                    first_seen_at=message.published_at,
                    last_resolved_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        if len(profiles) > 1:
            for index, left in enumerate(profiles):
                for right in profiles[index + 1 :]:
                    await self._relation(left.id, right.id, "co_occurring_contact", message.id, {})
        if phones and message.telegram_sender_id is not None:
            telegram = await self._existing_telegram_profile(message.telegram_sender_id)
            if telegram:
                for profile in profiles:
                    if profile.id != telegram.id:
                        await self._relation(
                            telegram.id, profile.id, "shared_sender", message.id, {}
                        )
        if is_provider:
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
        affected_profiles.update(await self._profiles_linked_to_vehicles(affected_vehicles))
        for profile_id in affected_profiles:
            await self._refresh_profile(profile_id)
            await self._refresh_identifiers(profile_id)
        for vehicle_id in affected_vehicles:
            await self._refresh_vehicle(vehicle_id)
        await self._refresh_links(affected_profiles)
        await self._refresh_shared_vehicle_observations(affected_vehicles)
        await self._refresh_relations(affected_profiles)
        if not await self._complete(job):
            await self._session.rollback()
            return "stale"
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
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"profile-phone:{entity.normalized_value}"},
        )
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
                first_seen_at=message.published_at,
                last_seen_at=message.published_at,
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
                    first_seen_at=message.published_at,
                    last_seen_at=message.published_at,
                    occurrence_count=0,
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
        sender_id = message.telegram_sender_id or 0
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"profile-telegram:{sender_id}"},
        )
        existing = await self._existing_telegram_profile(sender_id)
        now = datetime.now(timezone.utc)
        profile = existing
        if profile is None:
            profile = TransportProfile(
                profile_kind="telegram",
                canonical_label=f"Telegram-профиль {message.telegram_sender_id}",
                status="active",
                first_seen_at=message.published_at,
                last_seen_at=message.published_at,
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
                    first_seen_at=message.published_at,
                    last_seen_at=message.published_at,
                    occurrence_count=0,
                    created_at=now,
                    updated_at=now,
                )
            )
        if message.sender and message.sender.username:
            username = message.sender.username.casefold()
            alias = await self._session.scalar(
                select(ProfileIdentifier).where(
                    ProfileIdentifier.profile_id == profile.id,
                    ProfileIdentifier.identifier_type == "telegram_username",
                    ProfileIdentifier.identifier_role == "observed",
                    ProfileIdentifier.normalized_value == username,
                )
            )
            if alias is None:
                self._session.add(
                    ProfileIdentifier(
                        profile_id=profile.id,
                        identifier_type="telegram_username",
                        identifier_role="observed",
                        raw_value=message.sender.username,
                        normalized_value=username,
                        confidence=1.0,
                        source_message_id=message.id,
                        first_seen_at=message.published_at,
                        last_seen_at=message.published_at,
                        occurrence_count=0,
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
        self,
        profile_a: int,
        profile_b: int,
        kind: str,
        message_id: int,
        evidence: dict[str, object],
    ) -> None:
        if profile_a == profile_b:
            return
        left, right = sorted((profile_a, profile_b))
        now = datetime.now(timezone.utc)
        stmt = insert(ProfileRelationObservation).values(
            left_profile_id=left,
            right_profile_id=right,
            relation_type=kind,
            message_id=message_id,
            confidence=1.0,
            evidence=evidence,
            observed_at=(
                await self._session.scalar(
                    select(TelegramMessage.published_at).where(TelegramMessage.id == message_id)
                )
            ),
            created_at=now,
        )
        await self._session.execute(stmt.on_conflict_do_nothing())

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
        if entities and high_plates and (len(entities) != 1 or len(high_plates) != 1):
            await self._record_conflict(
                message.id,
                "ambiguous_vehicle_plate_mapping",
                {"vehicle_count": len(entities), "plate_count": len(high_plates)},
            )
        if len(entities) == 1 and len(high_plates) == 1:
            vehicle = await self._plate_vehicle(
                high_plates[0], entities[0].metadata_, message.published_at, message.id
            )
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
                vehicle = await self._plate_vehicle(plate, {}, message.published_at, message.id)
                await self._observe_vehicle(
                    vehicle, message, profiles, "alpr", None, plate.id, plate.confidence or 0
                )
            for entity in entities:
                for profile in profiles:
                    vehicle = await self._signature_vehicle(
                        profile.id, entity.metadata_, message.published_at
                    )
                    await self._observe_vehicle(
                        vehicle, message, [profile], "text", entity.id, None, entity.confidence
                    )

    async def _record_conflict(
        self, message_id: int, conflict_type: str, details: dict[str, object]
    ) -> None:
        """Upsert detection details while preserving an analyst's decision fields."""
        canonical_details = json.dumps(details, ensure_ascii=False, sort_keys=True, default=str)
        conflict_key = hashlib.sha256(
            f"{message_id}:{conflict_type}:{canonical_details}".encode("utf-8")
        ).hexdigest()
        now = datetime.now(timezone.utc)
        statement = insert(ProfileResolutionConflict).values(
            message_id=message_id,
            conflict_type=conflict_type,
            conflict_key=conflict_key,
            status="open",
            details=details,
            created_at=now,
            updated_at=now,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[ProfileResolutionConflict.conflict_key],
                set_={"details": details, "updated_at": now},
            )
        )

    async def _plate_vehicle(
        self,
        plate: PlateDetection,
        metadata: dict[str, object],
        observed_at: datetime,
        message_id: int,
    ) -> Vehicle:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"vehicle-plate:{plate.normalized_text}"},
        )
        vehicle = await self._session.scalar(
            select(Vehicle)
            .where(Vehicle.normalized_plate == plate.normalized_text)
            .with_for_update()
        )
        if vehicle:
            conflicts = {
                key: {"existing": getattr(vehicle, key), "observed": value}
                for key, value in metadata.items()
                if value is not None and getattr(vehicle, key) not in (None, value)
            }
            if conflicts:
                await self._record_conflict(
                    message_id,
                    "vehicle_identity_conflict",
                    {"vehicle_id": vehicle.id, "fields": conflicts},
                )
            else:
                for key, value in metadata.items():
                    if value is not None and getattr(vehicle, key) is None:
                        setattr(vehicle, key, value)
                vehicle.updated_at = datetime.now(timezone.utc)
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
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            observation_count=0,
            created_at=now,
            updated_at=now,
        )
        self._session.add(vehicle)
        await self._session.flush()
        return vehicle

    async def _signature_vehicle(
        self, profile_id: int, metadata: dict[str, object], observed_at: datetime
    ) -> Vehicle:
        signature = {key: metadata.get(key) for key in ("make", "model", "generation", "year")}
        signature_key = hashlib.sha256(
            json.dumps([profile_id, signature], sort_keys=True, default=str).encode()
        ).hexdigest()
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"vehicle-signature:{signature_key}"},
        )
        existing = await self._session.scalar(
            select(Vehicle).where(Vehicle.profile_signature_key == signature_key).with_for_update()
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
            profile_signature_key=signature_key,
            **signature,
            canonical_label=" ".join(parts) or "Неопределённый автомобиль",
            first_seen_at=observed_at,
            last_seen_at=observed_at,
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
        self._session.add(
            VehicleObservation(
                vehicle_id=vehicle.id,
                message_id=message.id,
                profile_id=None,
                source_type=source_type,
                extracted_entity_id=entity_id,
                plate_detection_id=plate_id,
                confidence=confidence,
                evidence={"message_id": message.id},
                observed_at=message.published_at,
                created_at=now,
                updated_at=now,
            )
        )
        for profile in profiles:
            await self._session.execute(
                insert(ProfileVehicleLinkObservation)
                .values(
                    profile_id=profile.id,
                    vehicle_id=vehicle.id,
                    message_id=message.id,
                    confidence=confidence,
                    evidence={"source_type": source_type},
                    observed_at=message.published_at,
                    created_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["profile_id", "vehicle_id", "message_id"],
                    set_={"confidence": confidence, "evidence": {"source_type": source_type}},
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
                func.max(ProfileOccurrence.first_seen_at),
            ).where(ProfileOccurrence.profile_id == profile_id)
        )
        total, active, first, last = rows.one()
        await self._session.execute(
            update(TransportProfile)
            .where(TransportProfile.id == profile_id)
            .values(
                occurrence_count=total,
                active_occurrence_count=active,
                first_seen_at=func.coalesce(first, TransportProfile.first_seen_at),
                last_seen_at=func.coalesce(last, TransportProfile.last_seen_at),
                updated_at=datetime.now(timezone.utc),
            )
        )

    async def _refresh_vehicle(self, vehicle_id: int) -> None:
        total, first, last = (
            await self._session.execute(
                select(
                    func.count(VehicleObservation.id),
                    func.min(VehicleObservation.observed_at),
                    func.max(VehicleObservation.observed_at),
                ).where(VehicleObservation.vehicle_id == vehicle_id)
            )
        ).one()
        await self._session.execute(
            update(Vehicle)
            .where(Vehicle.id == vehicle_id)
            .values(
                observation_count=total,
                first_seen_at=func.coalesce(first, Vehicle.first_seen_at),
                last_seen_at=func.coalesce(last, Vehicle.last_seen_at),
                updated_at=datetime.now(timezone.utc),
            )
        )

    async def _profiles_linked_to_vehicles(self, vehicle_ids: set[int]) -> set[int]:
        if not vehicle_ids:
            return set()
        return set(
            (
                await self._session.scalars(
                    select(ProfileVehicleLinkObservation.profile_id)
                    .where(ProfileVehicleLinkObservation.vehicle_id.in_(vehicle_ids))
                    .distinct()
                )
            ).all()
        )

    async def _refresh_identifiers(self, profile_id: int) -> None:
        identifiers = list(
            (
                await self._session.scalars(
                    select(ProfileIdentifier).where(ProfileIdentifier.profile_id == profile_id)
                )
            ).all()
        )
        now = datetime.now(timezone.utc)
        for identifier in identifiers:
            statement = (
                select(
                    func.count(func.distinct(ProfileOccurrence.message_id)),
                    func.min(TelegramMessage.published_at),
                    func.max(TelegramMessage.published_at),
                )
                .join(TelegramMessage, TelegramMessage.id == ProfileOccurrence.message_id)
                .where(ProfileOccurrence.profile_id == profile_id)
            )
            if identifier.identifier_type == "phone":
                statement = (
                    statement.join(
                        MessageAnalysis, MessageAnalysis.message_id == TelegramMessage.id
                    )
                    .join(ExtractedEntity, ExtractedEntity.analysis_id == MessageAnalysis.id)
                    .where(
                        ExtractedEntity.id == ProfileOccurrence.evidence["entity_id"].as_integer(),
                        ExtractedEntity.normalized_value == identifier.normalized_value,
                    )
                )
            elif identifier.identifier_type == "telegram_user_id":
                statement = statement.where(
                    TelegramMessage.telegram_sender_id == int(identifier.normalized_value)
                )
            elif identifier.identifier_type == "telegram_username":
                sender_id = await self._session.scalar(
                    select(ProfileIdentifier.normalized_value).where(
                        ProfileIdentifier.profile_id == profile_id,
                        ProfileIdentifier.identifier_type == "telegram_user_id",
                        ProfileIdentifier.identifier_role == "anchor",
                    )
                )
                if sender_id is None:
                    continue
                statement = statement.where(TelegramMessage.telegram_sender_id == int(sender_id))
            else:
                continue
            count, first, last = (await self._session.execute(statement)).one()
            identifier.occurrence_count = count or 0
            if count:
                identifier.first_seen_at = first
                identifier.last_seen_at = last
            identifier.updated_at = now

    async def _refresh_links(self, profile_ids: set[int]) -> None:
        if not profile_ids:
            return
        await self._session.execute(
            delete(ProfileVehicleLink).where(ProfileVehicleLink.profile_id.in_(profile_ids))
        )
        rows = await self._session.execute(
            select(
                ProfileVehicleLinkObservation.profile_id,
                ProfileVehicleLinkObservation.vehicle_id,
                func.count(),
                func.min(ProfileVehicleLinkObservation.observed_at),
                func.max(ProfileVehicleLinkObservation.observed_at),
                func.max(ProfileVehicleLinkObservation.confidence),
            )
            .where(ProfileVehicleLinkObservation.profile_id.in_(profile_ids))
            .group_by(
                ProfileVehicleLinkObservation.profile_id, ProfileVehicleLinkObservation.vehicle_id
            )
        )
        now = datetime.now(timezone.utc)
        for profile_id, vehicle_id, count, first, last, confidence in rows:
            self._session.add(
                ProfileVehicleLink(
                    profile_id=profile_id,
                    vehicle_id=vehicle_id,
                    first_seen_at=first,
                    last_seen_at=last,
                    occurrence_count=count,
                    confidence=confidence,
                    evidence={},
                    created_at=now,
                    updated_at=now,
                )
            )

    async def _refresh_shared_vehicle_observations(self, vehicle_ids: set[int]) -> None:
        now = datetime.now(timezone.utc)
        for vehicle_id in vehicle_ids:
            await self._session.execute(
                delete(ProfileSharedVehicleObservation).where(
                    ProfileSharedVehicleObservation.vehicle_id == vehicle_id
                )
            )
            rows = (
                await self._session.execute(
                    select(
                        ProfileVehicleLinkObservation.profile_id,
                        func.min(ProfileVehicleLinkObservation.observed_at),
                        func.max(ProfileVehicleLinkObservation.observed_at),
                        func.max(ProfileVehicleLinkObservation.confidence),
                    )
                    .where(ProfileVehicleLinkObservation.vehicle_id == vehicle_id)
                    .group_by(ProfileVehicleLinkObservation.profile_id)
                )
            ).all()
            for index, (left, left_first, left_last, left_confidence) in enumerate(rows):
                for right, right_first, right_last, right_confidence in rows[index + 1 :]:
                    self._session.add(
                        ProfileSharedVehicleObservation(
                            left_profile_id=min(left, right),
                            right_profile_id=max(left, right),
                            vehicle_id=vehicle_id,
                            confidence=max(left_confidence, right_confidence),
                            evidence={"vehicle_id": vehicle_id},
                            first_seen_at=min(left_first, right_first),
                            last_seen_at=max(left_last, right_last),
                            created_at=now,
                            updated_at=now,
                        )
                    )

    async def _refresh_relations(self, profile_ids: set[int]) -> None:
        if not profile_ids:
            return
        await self._session.execute(
            delete(ProfileRelation).where(
                (ProfileRelation.left_profile_id.in_(profile_ids))
                | (ProfileRelation.right_profile_id.in_(profile_ids))
            )
        )
        rows = await self._session.execute(
            select(
                ProfileRelationObservation.left_profile_id,
                ProfileRelationObservation.right_profile_id,
                ProfileRelationObservation.relation_type,
                func.count(),
                func.min(ProfileRelationObservation.observed_at),
                func.max(ProfileRelationObservation.observed_at),
                func.max(ProfileRelationObservation.confidence),
            )
            .where(
                (ProfileRelationObservation.left_profile_id.in_(profile_ids))
                | (ProfileRelationObservation.right_profile_id.in_(profile_ids))
            )
            .group_by(
                ProfileRelationObservation.left_profile_id,
                ProfileRelationObservation.right_profile_id,
                ProfileRelationObservation.relation_type,
            )
        )
        now = datetime.now(timezone.utc)
        for left, right, kind, count, first, last, confidence in rows:
            self._session.add(
                ProfileRelation(
                    left_profile_id=left,
                    right_profile_id=right,
                    relation_type=kind,
                    confidence=confidence,
                    first_seen_at=first,
                    last_seen_at=last,
                    occurrence_count=count,
                    evidence={"source_count": count},
                    created_at=now,
                    updated_at=now,
                )
            )
        shared_rows = (
            await self._session.execute(
                select(
                    ProfileSharedVehicleObservation.left_profile_id,
                    ProfileSharedVehicleObservation.right_profile_id,
                    ProfileSharedVehicleObservation.vehicle_id,
                    ProfileSharedVehicleObservation.first_seen_at,
                    ProfileSharedVehicleObservation.last_seen_at,
                    ProfileSharedVehicleObservation.confidence,
                ).where(
                    (ProfileSharedVehicleObservation.left_profile_id.in_(profile_ids))
                    | (ProfileSharedVehicleObservation.right_profile_id.in_(profile_ids))
                )
            )
        ).all()
        grouped: dict[tuple[int, int], list[tuple[int, datetime, datetime, float]]] = {}
        for left, right, vehicle_id, first, last, confidence in shared_rows:
            grouped.setdefault((left, right), []).append((vehicle_id, first, last, confidence))
        for (left, right), sources in grouped.items():
            self._session.add(
                ProfileRelation(
                    left_profile_id=left,
                    right_profile_id=right,
                    relation_type="shared_vehicle",
                    confidence=max(source[3] for source in sources),
                    first_seen_at=min(source[1] for source in sources),
                    last_seen_at=max(source[2] for source in sources),
                    occurrence_count=len(sources),
                    evidence={
                        "vehicle_ids": sorted(source[0] for source in sources),
                        "source_count": len(sources),
                    },
                    created_at=now,
                    updated_at=now,
                )
            )

    async def _complete(self, job: ProfileResolutionJob) -> bool:
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
        return bool(result.rowcount)

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
