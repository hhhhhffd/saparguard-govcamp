from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session


async def db_session(session: AsyncSession = Depends(get_session)) -> AsyncIterator[AsyncSession]:
    yield session
