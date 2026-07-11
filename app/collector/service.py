from __future__ import annotations

import asyncio
import logging

from telethon import events
from telethon.errors import FloodWaitError

from app.collector.client import authorize_client, build_client
from app.collector.handlers import handle_deleted_message, handle_edited_message, handle_new_message
from app.core.config import settings
from app.core.logging import configure_logging
from app.processing.media.worker import run_media_worker
from app.collector.sync import synchronize_configured_sources

logger = logging.getLogger(__name__)


async def run() -> None:
    """Run an independent, reconnecting Telethon collector process."""
    configure_logging(settings)
    client = build_client(settings)
    client.add_event_handler(handle_new_message, events.NewMessage())
    client.add_event_handler(handle_edited_message, events.MessageEdited())
    client.add_event_handler(handle_deleted_message, events.MessageDeleted())
    while True:
        try:
            logger.info("Connecting collector to Telegram")
            await authorize_client(client, settings)
            logger.info("Collector connected to Telegram")
            await synchronize_configured_sources(client, synchronize_existing=True)
            worker_tasks = [
                asyncio.create_task(run_media_worker(client), name=f"media-worker-{index}")
                for index in range(settings.alpr_worker_count)
            ]
            try:
                while await client.is_user_authorized():
                    await asyncio.sleep(settings.collector_reconnect_delay_seconds)
                    await synchronize_configured_sources(client, synchronize_existing=False)
            finally:
                for task in worker_tasks:
                    task.cancel()
                await asyncio.gather(*worker_tasks, return_exceptions=True)
        except FloodWaitError as exc:
            logger.warning("Telegram requested FloodWait: sleeping for %s seconds", exc.seconds)
            await asyncio.sleep(exc.seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Collector connection cycle failed; reconnecting")
            await asyncio.sleep(settings.collector_reconnect_delay_seconds)
        finally:
            if client.is_connected():
                await client.disconnect()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Collector stopped")


if __name__ == "__main__":
    main()
