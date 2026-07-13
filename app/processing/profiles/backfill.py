from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database.models import MessageAnalysis, TelegramMessage
from app.database.session import SessionFactory
from app.processing.profiles.repository import PROVIDER_TYPES, ProfileResolutionRepository


async def run(days: int, limit: int | None, force: bool, only_provider_messages: bool) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    seen = enqueued = skipped = providers = unresolved = 0
    last_id = 0
    while limit is None or seen < limit:
        batch_size = min(200, (limit - seen) if limit is not None else 200)
        async with SessionFactory.begin() as session:
            statement = (
                select(TelegramMessage.id, MessageAnalysis.message_type)
                .outerjoin(MessageAnalysis)
                .where(TelegramMessage.published_at >= cutoff, TelegramMessage.id > last_id)
                .order_by(TelegramMessage.id)
                .limit(batch_size)
            )
            if only_provider_messages:
                statement = statement.where(MessageAnalysis.message_type.in_(PROVIDER_TYPES))
            rows = (await session.execute(statement)).all()
            if not rows:
                break
            repository = ProfileResolutionRepository(session)
            for message_id, message_type in rows:
                seen += 1
                last_id = message_id
                if message_type in PROVIDER_TYPES:
                    providers += 1
                if message_type is None:
                    unresolved += 1
                if await repository.enqueue_for_message(message_id, force=force):
                    enqueued += 1
                else:
                    skipped += 1
    print(
        f"viewed={seen} enqueued={enqueued} skipped={skipped} provider_messages={providers} unresolved_messages={unresolved}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Queue profile resolution for recent messages")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--only-provider-messages", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.days, args.limit, args.force, args.only_provider_messages))


if __name__ == "__main__":
    main()
