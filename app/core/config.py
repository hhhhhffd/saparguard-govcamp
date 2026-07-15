from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_api_id: int | None = Field(default=None, validation_alias="TELEGRAM_API_ID")
    telegram_api_hash: str | None = Field(default=None, validation_alias="TELEGRAM_API_HASH")
    telegram_session_path: Path = Field(
        default=Path("./data/telethon.session"), validation_alias="TELEGRAM_SESSION_PATH"
    )
    telegram_auth_mode: Literal["phone", "qr"] = Field(
        default="phone", validation_alias="TELEGRAM_AUTH_MODE"
    )
    display_timezone: str = Field(default="Asia/Almaty", validation_alias="DISPLAY_TIMEZONE")
    database_url: PostgresDsn = Field(validation_alias="DATABASE_URL")
    api_host: str = Field(default="0.0.0.0", validation_alias="API_HOST")
    api_port: int = Field(default=8000, validation_alias="API_PORT")
    jwt_secret: str = Field(default="", validation_alias="JWT_SECRET")
    jwt_expire_minutes: int = Field(default=480, ge=1, validation_alias="JWT_EXPIRE_MINUTES")
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    jwt_cookie_name: str = Field(default="saparguard_session", validation_alias="JWT_COOKIE_NAME")
    jwt_cookie_secure: bool = Field(default=False, validation_alias="JWT_COOKIE_SECURE")
    default_admin_email: str | None = Field(default=None, validation_alias="DEFAULT_ADMIN_EMAIL")
    default_admin_password: str | None = Field(default=None, validation_alias="DEFAULT_ADMIN_PASSWORD")
    google_client_id: str | None = Field(default=None, validation_alias="GOOGLE_CLIENT_ID")
    google_client_secret: str | None = Field(default=None, validation_alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str | None = Field(default=None, validation_alias="GOOGLE_REDIRECT_URI")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    log_path: Path = Field(default=Path("./logs/saparguard.log"), validation_alias="LOG_PATH")
    collector_reconnect_delay_seconds: int = Field(
        default=10, validation_alias="COLLECTOR_RECONNECT_DELAY_SECONDS"
    )
    collector_history_batch_size: int = Field(
        default=100, validation_alias="COLLECTOR_HISTORY_BATCH_SIZE"
    )
    collector_history_days: int = Field(default=7, ge=1, validation_alias="COLLECTOR_HISTORY_DAYS")
    # FastALPR is a process-global lazy instance; concurrency waits for a thread-safety review.
    alpr_worker_count: int = Field(default=1, ge=1, validation_alias="ALPR_WORKER_COUNT")
    media_job_max_attempts: int = Field(default=3, ge=1, validation_alias="MEDIA_JOB_MAX_ATTEMPTS")
    media_job_retry_delay_seconds: int = Field(
        default=60, ge=1, validation_alias="MEDIA_JOB_RETRY_DELAY_SECONDS"
    )
    media_job_stale_timeout_seconds: int = Field(
        default=900, ge=1, validation_alias="MEDIA_JOB_STALE_TIMEOUT_SECONDS"
    )
    media_storage_path: Path = Field(
        default=Path("./data/media"), validation_alias="MEDIA_STORAGE_PATH"
    )
    text_analysis_job_max_attempts: int = Field(
        default=3, ge=1, validation_alias="TEXT_ANALYSIS_JOB_MAX_ATTEMPTS"
    )
    text_analysis_job_retry_delay_seconds: int = Field(
        default=60, ge=1, validation_alias="TEXT_ANALYSIS_JOB_RETRY_DELAY_SECONDS"
    )
    text_analysis_job_stale_timeout_seconds: int = Field(
        default=900, ge=1, validation_alias="TEXT_ANALYSIS_JOB_STALE_TIMEOUT_SECONDS"
    )
    text_analysis_poll_interval_seconds: int = Field(
        default=2, ge=1, validation_alias="TEXT_ANALYSIS_POLL_INTERVAL_SECONDS"
    )
    text_analyzer_version: str = Field(
        default="20260714.1", validation_alias="TEXT_ANALYZER_VERSION"
    )
    profile_resolver_version: str = Field(
        default="profile-v1", validation_alias="PROFILE_RESOLVER_VERSION"
    )
    profile_job_max_attempts: int = Field(
        default=5, ge=1, validation_alias="PROFILE_JOB_MAX_ATTEMPTS"
    )
    profile_job_retry_delay_seconds: int = Field(
        default=30, ge=1, validation_alias="PROFILE_JOB_RETRY_DELAY_SECONDS"
    )
    profile_job_stale_timeout_seconds: int = Field(
        default=900, ge=1, validation_alias="PROFILE_JOB_STALE_TIMEOUT_SECONDS"
    )
    profile_job_poll_interval_seconds: int = Field(
        default=2, ge=1, validation_alias="PROFILE_JOB_POLL_INTERVAL_SECONDS"
    )
    profile_job_recovery_interval_seconds: int = Field(
        default=60, ge=1, validation_alias="PROFILE_JOB_RECOVERY_INTERVAL_SECONDS"
    )
    profile_plate_min_confidence: float = Field(
        default=0.80, ge=0, le=1, validation_alias="PROFILE_PLATE_MIN_CONFIDENCE"
    )
    profile_sender_relay_distinct_phone_limit: int = Field(
        default=3, ge=1, validation_alias="PROFILE_SENDER_RELAY_DISTINCT_PHONE_LIMIT"
    )


settings = Settings()
