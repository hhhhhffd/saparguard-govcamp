from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base


class TransportProfile(Base):
    __tablename__ = "transport_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_label: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resolver_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProfileIdentifier(Base):
    __tablename__ = "profile_identifiers"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("transport_profiles.id"), nullable=False)
    identifier_type: Mapped[str] = mapped_column(String(32), nullable=False)
    identifier_role: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey("telegram_messages.id"))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProfileOccurrence(Base):
    __tablename__ = "profile_occurrences"
    __table_args__ = (UniqueConstraint("profile_id", "message_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("transport_profiles.id"), nullable=False)
    message_id: Mapped[int] = mapped_column(ForeignKey("telegram_messages.id"), nullable=False)
    match_method: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_deleted: Mapped[bool] = mapped_column(nullable=False, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProfileRelation(Base):
    __tablename__ = "profile_relations"
    __table_args__ = (
        CheckConstraint(
            "left_profile_id < right_profile_id", name="ck_profile_relations_canonical_pair"
        ),
        UniqueConstraint("left_profile_id", "right_profile_id", "relation_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    left_profile_id: Mapped[int] = mapped_column(
        ForeignKey("transport_profiles.id"), nullable=False
    )
    right_profile_id: Mapped[int] = mapped_column(
        ForeignKey("transport_profiles.id"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    identity_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_plate: Mapped[str | None] = mapped_column(String(128), unique=True)
    make: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(128))
    generation: Mapped[str | None] = mapped_column(String(128))
    year: Mapped[int | None] = mapped_column(Integer)
    canonical_label: Mapped[str] = mapped_column(String(255), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VehicleObservation(Base):
    __tablename__ = "vehicle_observations"
    __table_args__ = (
        UniqueConstraint(
            "vehicle_id",
            "message_id",
            "source_type",
            "extracted_entity_id",
            name="uq_vehicle_observation_text_source",
        ),
        UniqueConstraint(
            "vehicle_id",
            "message_id",
            "source_type",
            "plate_detection_id",
            name="uq_vehicle_observation_plate_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    message_id: Mapped[int] = mapped_column(ForeignKey("telegram_messages.id"), nullable=False)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("transport_profiles.id"))
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    extracted_entity_id: Mapped[int | None] = mapped_column(ForeignKey("extracted_entities.id"))
    plate_detection_id: Mapped[int | None] = mapped_column(ForeignKey("plate_detections.id"))
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProfileVehicleLink(Base):
    __tablename__ = "profile_vehicle_links"

    profile_id: Mapped[int] = mapped_column(ForeignKey("transport_profiles.id"), primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProfileResolutionConflict(Base):
    __tablename__ = "profile_resolution_conflicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_messages.id"), nullable=False, index=True
    )
    conflict_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProfileResolutionJob(Base):
    __tablename__ = "profile_resolution_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_messages.id"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    resolver_version: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_token: Mapped[str | None] = mapped_column(String(36), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
