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
    database_url: PostgresDsn = Field(validation_alias="DATABASE_URL")
    api_host: str = Field(default="0.0.0.0", validation_alias="API_HOST")
    api_port: int = Field(default=8000, validation_alias="API_PORT")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    log_path: Path = Field(default=Path("./logs/saparguard.log"), validation_alias="LOG_PATH")
    collector_reconnect_delay_seconds: int = Field(
        default=10, validation_alias="COLLECTOR_RECONNECT_DELAY_SECONDS"
    )
    collector_history_batch_size: int = Field(
        default=100, validation_alias="COLLECTOR_HISTORY_BATCH_SIZE"
    )


settings = Settings()
