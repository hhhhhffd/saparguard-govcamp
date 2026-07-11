from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.database.models import Base


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.getenv("POSTGRES_TEST_URL")
    if database_url is None:
        pytest.skip("POSTGRES_TEST_URL is required for PostgreSQL integration tests")
    if database_url == str(settings.database_url):
        pytest.fail("POSTGRES_TEST_URL must not point to the application database")
    database_name = make_url(database_url).database or ""
    if database_name not in {"test", "integration"} and not database_name.endswith(
        ("_test", "_integration")
    ):
        pytest.fail("POSTGRES_TEST_URL must use a dedicated database named *test or *integration")
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()
