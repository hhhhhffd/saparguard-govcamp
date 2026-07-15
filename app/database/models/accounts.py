"""Application accounts and citizen complaints.

These models intentionally do not reference Telegram identities.  They represent
people who use SaparGuard itself, not subjects observed by the collector.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base


class UserRole(StrEnum):
    CITIZEN = "citizen"
    WORKER = "worker"
    ADMIN = "admin"


class RegistrationSource(StrEnum):
    LOCAL = "local"
    GOOGLE = "google"


class ComplaintStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class AppUser(Base):
    __tablename__ = "app_users"

    __table_args__ = (
        CheckConstraint("role IN ('citizen', 'worker', 'admin')", name="ck_app_users_role"),
        CheckConstraint(
            "registration_source IN ('local', 'google')",
            name="ck_app_users_registration_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    normalized_email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=UserRole.CITIZEN.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    registration_source: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RegistrationSource.LOCAL.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Complaint(Base):
    __tablename__ = "complaints"

    __table_args__ = (
        CheckConstraint(
            "status IN ('new', 'in_progress', 'resolved', 'rejected')",
            name="ck_complaints_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(
        ForeignKey("app_users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ComplaintStatus.NEW.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status_changed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="RESTRICT"), nullable=True
    )


class ComplaintMedia(Base):
    __tablename__ = "complaint_media"

    id: Mapped[int] = mapped_column(primary_key=True)
    complaint_id: Mapped[int] = mapped_column(
        ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ComplaintStatusHistory(Base):
    __tablename__ = "complaint_status_history"

    __table_args__ = (
        CheckConstraint(
            "old_status IS NULL OR old_status IN ('new', 'in_progress', 'resolved', 'rejected')",
            name="ck_complaint_status_history_old_status",
        ),
        CheckConstraint(
            "new_status IN ('new', 'in_progress', 'resolved', 'rejected')",
            name="ck_complaint_status_history_new_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    complaint_id: Mapped[int] = mapped_column(
        ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    changed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="RESTRICT"), nullable=True
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
