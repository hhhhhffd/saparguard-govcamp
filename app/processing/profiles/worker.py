from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.database.session import SessionFactory
from app.processing.profiles.resolver import ProfileResolver
from app.processing.profiles.repository import ProfileResolutionRepository

logger = logging.getLogger(__name__)


async def process_one_job() -> bool:
    async with SessionFactory() as session:
        job = await ProfileResolutionRepository(session).claim_next_job()
    if job is None:
        return False
    try:
        async with SessionFactory() as session:
            outcome = await ProfileResolver(ProfileResolutionRepository(session)).resolve(job)
        logger.info("Profile job %s: %s", job.id, outcome)
    except Exception as exc:
        logger.exception("Profile job %s failed", job.id)
        async with SessionFactory() as session:
            await ProfileResolutionRepository(session).fail(job, str(exc))
    return True


async def run_worker() -> None:
    last_recovery = 0.0
    while True:
        now = asyncio.get_running_loop().time()
        if now - last_recovery >= settings.profile_job_recovery_interval_seconds:
            async with SessionFactory() as session:
                await ProfileResolutionRepository(session).recover_stale_jobs(
                    settings.profile_job_stale_timeout_seconds
                )
            last_recovery = now
        if not await process_one_job():
            await asyncio.sleep(settings.profile_job_poll_interval_seconds)


if __name__ == "__main__":
    asyncio.run(run_worker())
