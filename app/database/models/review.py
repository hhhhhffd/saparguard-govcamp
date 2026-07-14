from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base

if TYPE_CHECKING:
    from app.database.models.telegram import TelegramMessage


class MessageAnnotation(Base):
    """Human judgement, deliberately independent from automatic analysis."""

    __tablename__ = "message_annotations"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'reviewed', 'skipped')", name="ck_annotation_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_messages.id"), unique=True, nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    annotator: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_message_type: Mapped[str | None] = mapped_column(String(32))
    comment: Mapped[str | None] = mapped_column(Text)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    message: Mapped["TelegramMessage"] = relationship(back_populates="annotation")
    phones: Mapped[list["AnnotationPhone"]] = relationship(
        back_populates="annotation", cascade="all, delete-orphan"
    )
    routes: Mapped[list["AnnotationRoute"]] = relationship(
        back_populates="annotation", cascade="all, delete-orphan"
    )
    vehicles: Mapped[list["AnnotationVehicle"]] = relationship(
        back_populates="annotation", cascade="all, delete-orphan"
    )


class AnnotationPhone(Base):
    __tablename__ = "annotation_phones"
    __table_args__ = (UniqueConstraint("annotation_id", "normalized_value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    annotation_id: Mapped[int] = mapped_column(ForeignKey("message_annotations.id"), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(32), nullable=False)
    annotation: Mapped[MessageAnnotation] = relationship(back_populates="phones")


class AnnotationRoute(Base):
    __tablename__ = "annotation_routes"
    __table_args__ = (
        UniqueConstraint("annotation_id", "normalized_origin", "normalized_destination"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    annotation_id: Mapped[int] = mapped_column(ForeignKey("message_annotations.id"), nullable=False)
    normalized_origin: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_destination: Mapped[str] = mapped_column(String(255), nullable=False)
    annotation: Mapped[MessageAnnotation] = relationship(back_populates="routes")


class AnnotationVehicle(Base):
    __tablename__ = "annotation_vehicles"
    __table_args__ = (UniqueConstraint("annotation_id", "normalized_value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    annotation_id: Mapped[int] = mapped_column(ForeignKey("message_annotations.id"), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(255), nullable=False)
    annotation: Mapped[MessageAnnotation] = relationship(back_populates="vehicles")
