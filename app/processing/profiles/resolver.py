from __future__ import annotations

from app.database.models import ProfileResolutionJob
from app.processing.profiles.repository import ProfileResolutionRepository


class ProfileResolver:
    """Public resolver facade; persistence and lease handling stay in the repository."""

    def __init__(self, repository: ProfileResolutionRepository) -> None:
        self._repository = repository

    async def resolve(self, job: ProfileResolutionJob) -> str:
        return await self._repository.resolve(job)
