from __future__ import annotations

import random
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    AnnotationPhone,
    AnnotationRoute,
    AnnotationVehicle,
    ExtractedEntity,
    MediaFile,
    MessageAnalysis,
    MessageAnalysisJob,
    MessageAnnotation,
    MessageRoute,
    MediaProcessingJob,
    PlateDetection,
    ProfileResolutionJob,
    TelegramChat,
    TelegramMessage,
)

ANNOTATION_SCHEMA_VERSION = "1"
VALID_STATUSES = {"draft", "reviewed", "skipped"}
VALID_MESSAGE_TYPES = {
    "unknown",
    "conversation",
    "service_message",
    "commercial_spam",
    "parcel_request",
    "parcel_offer",
    "passenger_request",
    "driver_offer",
}
PHONE_DIGITS = re.compile(r"\D")
ROUTE_SEPARATOR = re.compile(r"\s*(?:->|→|—|–)\s*")


@dataclass(frozen=True)
class ReviewFilters:
    source_id: int | None = None
    annotation_status: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    message_type: str | None = None
    confidence_min: float | None = None
    confidence_max: float | None = None
    has_phone: bool | None = None
    has_route: bool | None = None
    has_vehicle: bool | None = None
    has_media: bool | None = None
    has_plate: bool | None = None
    processing_failed: bool = False
    unannotated_only: bool = False
    include_deleted: bool = False
    include_empty: bool = False


def normalize_phone(value: str) -> str:
    digits = PHONE_DIGITS.sub("", value)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if (digits.startswith("7") and len(digits) != 11) or (
        digits.startswith("996") and len(digits) != 12
    ):
        raise ValueError("Телефон должен быть нормализованным номером KZ/RU/KG")
    if not digits.startswith(("7", "996")):
        raise ValueError("Поддерживаются только номера KZ/RU (+7) и KG (+996)")
    return f"+{digits}"


def normalize_route_value(value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
    if not normalized or len(normalized) > 255:
        raise ValueError("Пункт маршрута обязателен и не должен быть длиннее 255 символов")
    return normalized


def normalize_vehicle(value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", value).replace("-", " ").split()).casefold()
    if not normalized or len(normalized) > 255:
        raise ValueError("Автомобиль обязателен и не должен быть длиннее 255 символов")
    return normalized


def normalize_message_type(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if normalized not in VALID_MESSAGE_TYPES:
        raise ValueError("Недопустимый тип сообщения")
    return normalized


def source_text_hash(text: str | None) -> str:
    return sha256((text or "").encode("utf-8")).hexdigest()


def annotation_is_stale(annotation: MessageAnnotation, text: str | None) -> bool:
    return annotation.source_text_hash != source_text_hash(text)


def normalize_route(value: str) -> tuple[str, str]:
    parts = ROUTE_SEPARATOR.split(unicodedata.normalize("NFKC", value).strip())
    if len(parts) != 2:
        raise ValueError("Маршрут должен иметь вид origin -> destination")
    return normalize_route_value(parts[0]), normalize_route_value(parts[1])


def normalize_annotation_values(
    phones: list[str], routes: list[str], vehicles: list[str]
) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    phones = [line for value in phones for line in value.splitlines()]
    routes = [line for value in routes for line in value.splitlines()]
    vehicles = [line for value in vehicles for line in value.splitlines()]
    normalized_phones = sorted({normalize_phone(value) for value in phones if value.strip()})
    normalized_routes: set[tuple[str, str]] = set()
    for value in routes:
        if not value.strip():
            continue
        normalized_routes.add(normalize_route(value))
    normalized_vehicles = sorted({normalize_vehicle(value) for value in vehicles if value.strip()})
    return normalized_phones, sorted(normalized_routes), normalized_vehicles


def _entity_exists(entity_type: str):
    return exists(
        select(ExtractedEntity.id).where(
            ExtractedEntity.analysis_id == MessageAnalysis.id,
            ExtractedEntity.entity_type == entity_type,
        )
    )


def _text_group(text: str | None) -> tuple[str, str]:
    value = (text or "").casefold()
    text_without_phones = re.sub(r"\+?\d[\d\s()./\-]{7,}\d", "[phone]", value)
    normalized = " ".join(re.sub(r"[^\w\s]", " ", text_without_phones).split())
    script = (
        "cyrillic"
        if re.search(r"[а-яёәіңғүұқөһ]", value)
        else "latin"
        if re.search(r"[a-z]", value)
        else "other"
    )
    return script, sha256(normalized.encode("utf-8")).hexdigest()[:12]


async def select_review_queue(
    session: AsyncSession, filters: ReviewFilters, *, limit: int, seed: int
) -> list[int]:
    """Return reproducible, balanced candidates without persisting a queue."""
    predicates = []
    if not filters.include_deleted:
        predicates.append(TelegramMessage.is_deleted.is_(False))
    if not filters.include_empty:
        predicates.append(TelegramMessage.text.is_not(None))
        predicates.append(TelegramMessage.text != "")
    if filters.source_id is not None:
        predicates.append(TelegramChat.id == filters.source_id)
    if filters.date_from:
        predicates.append(TelegramMessage.published_at >= filters.date_from)
    if filters.date_to:
        predicates.append(TelegramMessage.published_at <= filters.date_to)
    if filters.message_type:
        predicates.append(MessageAnalysis.message_type == filters.message_type)
    if filters.confidence_min is not None:
        predicates.append(MessageAnalysis.classification_confidence >= filters.confidence_min)
    if filters.confidence_max is not None:
        predicates.append(MessageAnalysis.classification_confidence <= filters.confidence_max)
    for expected, condition in (
        (filters.has_phone, _entity_exists("phone")),
        (filters.has_vehicle, _entity_exists("vehicle")),
        (
            filters.has_route,
            exists(select(MessageRoute.id).where(MessageRoute.analysis_id == MessageAnalysis.id)),
        ),
        (
            filters.has_media,
            exists(select(MediaFile.id).where(MediaFile.message_id == TelegramMessage.id)),
        ),
        (
            filters.has_plate,
            exists(
                select(PlateDetection.id)
                .join(MediaFile)
                .where(MediaFile.message_id == TelegramMessage.id)
            ),
        ),
    ):
        if expected is not None:
            predicates.append(condition if expected else ~condition)
    if filters.processing_failed:
        predicates.append(
            or_(
                MessageAnalysisJob.status == "failed",
                MediaProcessingJob.status == "failed",
                ProfileResolutionJob.status == "failed",
            )
        )
    if filters.unannotated_only:
        predicates.append(MessageAnnotation.id.is_(None))
    if filters.annotation_status == "unreviewed":
        predicates.append(MessageAnnotation.id.is_(None))
    elif filters.annotation_status in VALID_STATUSES:
        predicates.append(MessageAnnotation.status == filters.annotation_status)

    rows = (
        await session.execute(
            select(
                TelegramMessage.id,
                TelegramMessage.telegram_chat_id,
                MessageAnalysis.message_type,
                MessageAnalysis.classification_confidence,
                TelegramMessage.text,
                select(func.count(ExtractedEntity.id))
                .where(
                    ExtractedEntity.analysis_id == MessageAnalysis.id,
                    ExtractedEntity.entity_type == "phone",
                )
                .scalar_subquery(),
                _entity_exists("vehicle"),
                exists(
                    select(MessageRoute.id).where(MessageRoute.analysis_id == MessageAnalysis.id)
                ),
                MessageAnnotation.source_text_hash,
                exists(select(MediaFile.id).where(MediaFile.message_id == TelegramMessage.id)),
                exists(
                    select(PlateDetection.id)
                    .join(MediaFile)
                    .where(MediaFile.message_id == TelegramMessage.id)
                ),
            )
            .outerjoin(MessageAnalysis)
            .outerjoin(
                TelegramChat, TelegramChat.telegram_chat_id == TelegramMessage.telegram_chat_id
            )
            .outerjoin(MessageAnnotation)
            .outerjoin(MessageAnalysisJob)
            .outerjoin(MediaProcessingJob, MediaProcessingJob.message_id == TelegramMessage.id)
            .outerjoin(ProfileResolutionJob, ProfileResolutionJob.message_id == TelegramMessage.id)
            .where(and_(*predicates))
            .distinct()
            .order_by(TelegramMessage.id)
        )
    ).all()
    sampling_rows = []
    for row in rows:
        (
            message_id,
            source,
            message_type,
            confidence,
            text,
            phone_count,
            has_vehicle,
            has_route,
            annotation_hash,
            has_media,
            has_plate,
        ) = row
        if filters.annotation_status == "stale" and (
            annotation_hash is None or annotation_hash == source_text_hash(text)
        ):
            continue
        sampling_rows.append(
            (
                message_id,
                source,
                message_type,
                confidence,
                text,
                phone_count,
                has_vehicle,
                has_route,
                has_media,
                has_plate,
            )
        )
    return stratified_sample(sampling_rows, limit=limit, seed=seed)


def stratified_sample(rows: list[object], *, limit: int, seed: int) -> list[int]:
    """Sample one item per source/type/confidence/length stratum before repeating."""
    buckets: dict[tuple[object, ...], list[int]] = defaultdict(list)
    for (
        message_id,
        source,
        message_type,
        confidence,
        text,
        phone_count,
        has_vehicle,
        has_route,
        has_media,
        has_plate,
    ) in rows:
        confidence_band = (
            "none"
            if confidence is None
            else "low"
            if confidence < 0.5
            else "medium"
            if confidence < 0.8
            else "high"
        )
        length_band = (
            "short" if len(text or "") < 80 else "long" if len(text or "") > 500 else "medium"
        )
        script_group, duplicate_group = _text_group(text)
        phone_band = "0" if not phone_count else "1" if phone_count == 1 else "2+"
        buckets[
            (
                source,
                message_type or "unanalysed",
                confidence_band,
                length_band,
                phone_band,
                bool(has_route),
                bool(has_vehicle),
                bool(has_media),
                bool(has_plate),
                script_group,
                duplicate_group,
            )
        ].append(message_id)
    rng = random.Random(seed)
    for values in buckets.values():
        values.sort()
        rng.shuffle(values)
    selected: list[int] = []
    while buckets and len(selected) < limit:
        seen_sources: set[object] = set()
        ordered_keys = sorted(list(buckets), key=str)
        for key in ordered_keys:
            if key[0] in seen_sources:
                continue
            if buckets[key] and len(selected) < limit:
                selected.append(buckets[key].pop())
                seen_sources.add(key[0])
            if not buckets[key]:
                del buckets[key]
        if not seen_sources:
            break
    return selected


async def get_review_message(session: AsyncSession, message_id: int) -> TelegramMessage | None:
    return await session.scalar(
        select(TelegramMessage)
        .where(TelegramMessage.id == message_id)
        .options(
            selectinload(TelegramMessage.chat),
            selectinload(TelegramMessage.sender),
            selectinload(TelegramMessage.media_files),
            selectinload(TelegramMessage.annotation).selectinload(MessageAnnotation.phones),
            selectinload(TelegramMessage.annotation).selectinload(MessageAnnotation.routes),
            selectinload(TelegramMessage.annotation).selectinload(MessageAnnotation.vehicles),
            selectinload(TelegramMessage.analysis).selectinload(MessageAnalysis.entities),
            selectinload(TelegramMessage.analysis).selectinload(MessageAnalysis.routes),
        )
    )


async def save_annotation(
    session: AsyncSession,
    *,
    message_id: int,
    status: str,
    annotator: str,
    message_type: str | None,
    phones: list[str],
    routes: list[str],
    vehicles: list[str],
    comment: str | None,
    source_text: str | None,
) -> MessageAnnotation:
    if status not in VALID_STATUSES:
        raise ValueError("Недопустимый статус разметки")
    if not annotator.strip() or len(annotator) > 255:
        raise ValueError("Укажите annotator")
    if status == "reviewed" and not message_type:
        raise ValueError("Для подтверждения нужен ожидаемый тип сообщения")
    values = normalize_annotation_values(phones, routes, vehicles)
    now = datetime.now(timezone.utc)
    annotation = await session.scalar(
        select(MessageAnnotation)
        .where(MessageAnnotation.message_id == message_id)
        .options(
            selectinload(MessageAnnotation.phones),
            selectinload(MessageAnnotation.routes),
            selectinload(MessageAnnotation.vehicles),
        )
    )
    if annotation is None:
        annotation = MessageAnnotation(
            message_id=message_id,
            annotator=annotator.strip(),
            status=status,
            expected_message_type=normalize_message_type(message_type) if message_type else None,
            comment=comment.strip() if comment else None,
            schema_version=ANNOTATION_SCHEMA_VERSION,
            source_text_hash=source_text_hash(source_text),
            created_at=now,
            updated_at=now,
            reviewed_at=now if status == "reviewed" else None,
        )
        session.add(annotation)
        await session.flush()
    else:
        annotation.status = status
        annotation.annotator = annotator.strip()
        annotation.expected_message_type = (
            normalize_message_type(message_type) if message_type else None
        )
        annotation.comment = comment.strip() if comment else None
        annotation.schema_version = ANNOTATION_SCHEMA_VERSION
        annotation.source_text_hash = source_text_hash(source_text)
        annotation.updated_at = now
        annotation.reviewed_at = now if status == "reviewed" else None
        annotation.phones.clear()
        annotation.routes.clear()
        annotation.vehicles.clear()
        await session.flush()
    annotation.phones.extend(AnnotationPhone(normalized_value=value) for value in values[0])
    annotation.routes.extend(
        AnnotationRoute(normalized_origin=origin, normalized_destination=destination)
        for origin, destination in values[1]
    )
    annotation.vehicles.extend(AnnotationVehicle(normalized_value=value) for value in values[2])
    return annotation
