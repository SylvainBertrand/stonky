"""Pytest fixtures for async database sessions.

Set TEST_DATABASE_URL env var (or use .env) to point at a dedicated test DB.
The session fixture rolls back after every test to keep isolation.
"""
import os
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://stonky:changeme@localhost:5432/stonky_test",
)


@pytest.fixture(scope="session")
async def db_engine():
    """Create all tables once per session; drop them on teardown."""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def session(db_engine) -> AsyncGenerator[AsyncSession, None]:  # type: ignore[no-untyped-def]
    """Per-test async session that rolls back after the test completes."""
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as s:
        yield s
        await s.rollback()
