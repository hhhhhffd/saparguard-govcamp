from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.database.repositories import MessageAnalysisJobRepository
from app.database.session import SessionFactory
from app.processing.text.analyzer import analyze_message

logger = logging.getLogger(__name__)


async def process_one_job() -> bool:
    async with SessionFactory() as session:
        job = await MessageAnalysisJobRepository(session).claim_next_job()
    if job is None:
        return False
    try:
        result = analyze_message(job.message.text)
        async with SessionFactory() as session:
            await MessageAnalysisJobRepository(session).complete(job, result)
        logger.info("Completed text analysis job %s", job.id)
    except Exception as exc:
        logger.exception("Text analysis job %s failed", job.id)
        async with SessionFactory() as session:
            await MessageAnalysisJobRepository(session).fail(
                job,
                str(exc),
                max_attempts=settings.text_analysis_job_max_attempts,
                retry_delay_seconds=settings.text_analysis_job_retry_delay_seconds,
            )
    return True


async def run_worker() -> None:
    async with SessionFactory() as session:
        recovered = await MessageAnalysisJobRepository(session).recover_stale_jobs(
            settings.text_analysis_job_stale_timeout_seconds
        )
    if recovered:
        logger.warning("Returned %s stale text analysis jobs to pending", recovered)
    while True:
        if not await process_one_job():
            await asyncio.sleep(settings.text_analysis_poll_interval_seconds)


if __name__ == "__main__":
    asyncio.run(run_worker())
