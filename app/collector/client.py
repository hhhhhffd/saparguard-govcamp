from __future__ import annotations

from telethon import TelegramClient

from app.config import Settings


def build_client(config: Settings) -> TelegramClient:
    """Build a user-session client; credentials are intentionally never logged."""
    if not config.telegram_api_id or not config.telegram_api_hash:
        raise RuntimeError("TELEGRAM_API_ID and TELEGRAM_API_HASH must be configured")
    config.telegram_session_path.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        str(config.telegram_session_path), config.telegram_api_id, config.telegram_api_hash
    )
