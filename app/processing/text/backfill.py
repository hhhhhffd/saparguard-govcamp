from __future__ import annotations

import argparse
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.database.models import TelegramMessage
from app.database.repositories import MessageAnalysisJobRepository
from app.database.session import SessionFactory


async def run(days: int | None, limit: int | None, force: bool) -> tuple[int, int, int]:
    scanned = queued = skipped = 0
    last_id = 0
    while limit is None or scanned < limit:
        async with SessionFactory.begin() as session:
            statement = (
                select(TelegramMessage)
                .where(TelegramMessage.id > last_id)
                .order_by(TelegramMessage.id)
                .limit(min(200, (limit - scanned) if limit else 200))
            )
            if days is not None:
                statement = statement.where(
                    TelegramMessage.published_at
                    >= datetime.now(timezone.utc) - timedelta(days=days)
                )
            messages = list((await session.scalars(statement)).all())
            if not messages:
                break
            repository = MessageAnalysisJobRepository(session)
            for message in messages:
                source_hash = hashlib.sha256((message.text or "").encode("utf-8")).hexdigest()
                if await repository.enqueue(
                    message.id, source_hash, settings.text_analyzer_version, force=force
                ):
                    queued += 1
                else:
                    skipped += 1
                scanned += 1
                last_id = message.id
    return scanned, queued, skipped


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Queue existing Telegram messages for text analysis"
    )
    parser.add_argument("--days", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    scanned, queued, skipped = asyncio.run(run(args.days, args.limit, args.force))
    print(f"scanned={scanned} queued={queued} skipped={skipped}")


if __name__ == "__main__":
    main()
