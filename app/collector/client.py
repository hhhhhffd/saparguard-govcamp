from __future__ import annotations

import asyncio
import getpass
import logging
import sys

import qrcode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from app.config import Settings

logger = logging.getLogger(__name__)


def build_client(config: Settings) -> TelegramClient:
    """Build a user-session client; credentials are intentionally never logged."""
    if not config.telegram_api_id or not config.telegram_api_hash:
        raise RuntimeError("TELEGRAM_API_ID and TELEGRAM_API_HASH must be configured")
    config.telegram_session_path.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        str(config.telegram_session_path), config.telegram_api_id, config.telegram_api_hash
    )


def display_qr_login(url: str) -> None:
    """Render a short-lived Telegram login token only in the interactive terminal."""
    code = qrcode.QRCode(border=1)
    code.add_data(url)
    code.make(fit=True)
    print("\nScan this QR in Telegram: Settings → Devices → Link Desktop Device.\n")
    code.print_ascii(invert=True)


async def authorize_client(client: TelegramClient, config: Settings) -> None:
    """Authorize a user session through the selected interactive method."""
    if config.telegram_auth_mode == "phone":
        await client.start()
        return

    await client.connect()
    if await client.is_user_authorized():
        return
    if not sys.stdin.isatty():
        raise RuntimeError("QR authorization requires an interactive terminal")

    while True:
        qr_login = await client.qr_login()
        display_qr_login(qr_login.url)
        try:
            user = await qr_login.wait()
            logger.info("QR authorization completed for Telegram user %s", user.id)
            return
        except SessionPasswordNeededError:
            password = getpass.getpass("Telegram 2FA password: ")
            user = await client.sign_in(password=password)
            logger.info("QR authorization with 2FA completed for Telegram user %s", user.id)
            return
        except asyncio.TimeoutError:
            logger.info("Telegram QR login token expired; generating a new code")
