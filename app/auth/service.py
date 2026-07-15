"""Small, explicit services for application authentication and account bootstrap."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database.models import AppUser, RegistrationSource, UserRole

logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 12


class AuthenticationError(ValueError):
    """Raised when credentials, tokens or required auth configuration are invalid."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_and_validate_email(email: str) -> tuple[str, str]:
    """Return a safe display value and stable value used for uniqueness checks."""
    try:
        validated = validate_email(email.strip(), check_deliverability=False)
    except EmailNotValidError as error:
        raise AuthenticationError("Укажите корректный email.") from error
    return validated.normalized, validated.normalized.casefold()


def normalize_email(email: str) -> str:
    """Return the validated normalized email retained by legacy callers."""
    return normalize_and_validate_email(email)[1]


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthenticationError(
            f"Пароль должен содержать не менее {MIN_PASSWORD_LENGTH} символов."
        )


def hash_password(password: str) -> str:
    validate_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (TypeError, ValueError):
        logger.warning("Stored password hash has an invalid format")
        return False


def require_jwt_configuration() -> None:
    if not settings.jwt_secret:
        raise RuntimeError("JWT_SECRET must be configured before starting SaparGuard")


def create_access_token(user: AppUser) -> str:
    require_jwt_configuration()
    now = utc_now()
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> int:
    require_jwt_configuration()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject.isdigit():
            raise AuthenticationError("JWT subject is invalid")
        return int(subject)
    except jwt.ExpiredSignatureError as error:
        raise AuthenticationError("JWT has expired") from error
    except jwt.PyJWTError as error:
        raise AuthenticationError("JWT is invalid") from error


async def get_active_user_by_id(session: AsyncSession, user_id: int) -> AppUser | None:
    user = await session.get(AppUser, user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        return None
    return user


async def register_local_user(session: AsyncSession, *, email: str, password: str) -> AppUser:
    validate_password(password)
    display_email, normalized_email = normalize_and_validate_email(email)
    existing = await session.scalar(
        select(AppUser).where(AppUser.normalized_email == normalized_email)
    )
    if existing is not None:
        raise AuthenticationError("Пользователь с таким email уже существует.")
    now = utc_now()
    user = AppUser(
        email=display_email,
        normalized_email=normalized_email,
        password_hash=hash_password(password),
        role=UserRole.CITIZEN.value,
        is_active=True,
        registration_source=RegistrationSource.LOCAL.value,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    await session.flush()
    return user


async def authenticate_local_user(
    session: AsyncSession, *, email: str, password: str
) -> AppUser | None:
    try:
        normalized_email = normalize_email(email)
    except AuthenticationError:
        return None
    user = await session.scalar(select(AppUser).where(AppUser.normalized_email == normalized_email))
    if user is None or not user.is_active or user.deleted_at is not None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    now = utc_now()
    user.last_login_at = now
    user.updated_at = now
    return user


async def link_google_account(
    session: AsyncSession,
    *,
    google_account_id: str,
    email: str,
    email_verified: bool,
) -> AppUser:
    """Link a verified Google identity to an existing account or create a citizen."""
    if not email_verified:
        raise AuthenticationError("Google не подтвердил email-адрес.")
    display_email, normalized_email = normalize_and_validate_email(email)
    user = await session.scalar(
        select(AppUser).where(AppUser.google_account_id == google_account_id)
    )
    if user is None:
        user = await session.scalar(
            select(AppUser).where(AppUser.normalized_email == normalized_email)
        )
        if user is not None:
            if user.google_account_id not in (None, google_account_id):
                raise AuthenticationError("Этот email уже связан с другим Google-аккаунтом.")
            user.google_account_id = google_account_id
        else:
            now = utc_now()
            user = AppUser(
                email=display_email,
                normalized_email=normalized_email,
                google_account_id=google_account_id,
                role=UserRole.CITIZEN.value,
                is_active=True,
                registration_source=RegistrationSource.GOOGLE.value,
                created_at=now,
                updated_at=now,
            )
            session.add(user)
            await session.flush()
    if not user.is_active or user.deleted_at is not None:
        raise AuthenticationError("Доступ к этой учётной записи заблокирован.")
    now = utc_now()
    user.last_login_at = now
    user.updated_at = now
    return user


async def bootstrap_default_admin(session: AsyncSession) -> AppUser | None:
    """Create the configured administrator once without ever rotating its password."""
    email = settings.default_admin_email
    password = settings.default_admin_password
    if not email and not password:
        return None
    if not email or not password:
        raise RuntimeError(
            "DEFAULT_ADMIN_EMAIL and DEFAULT_ADMIN_PASSWORD must be configured together"
        )
    validate_password(password)
    display_email, normalized_email = normalize_and_validate_email(email)
    existing = await session.scalar(
        select(AppUser).where(AppUser.normalized_email == normalized_email)
    )
    if existing is not None:
        if (
            existing.role == UserRole.ADMIN.value
            and existing.is_active
            and existing.deleted_at is None
        ):
            return existing
        state = []
        state.append(f"role={existing.role}")
        state.append("active" if existing.is_active else "blocked")
        state.append("deleted" if existing.deleted_at is not None else "not deleted")
        raise RuntimeError(
            "DEFAULT_ADMIN_EMAIL conflicts with existing account "
            f"{display_email} ({', '.join(state)}). Choose another DEFAULT_ADMIN_EMAIL "
            "or correct the account through the database or an administrator."
        )
    now = utc_now()
    admin = AppUser(
        email=display_email,
        normalized_email=normalized_email,
        password_hash=hash_password(password),
        role=UserRole.ADMIN.value,
        is_active=True,
        registration_source=RegistrationSource.LOCAL.value,
        created_at=now,
        updated_at=now,
    )
    session.add(admin)
    await session.flush()
    logger.info("Created configured default administrator account", extra={"email": admin.email})
    return admin
