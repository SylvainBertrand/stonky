"""
Pytest fixtures for the three-tier test suite.

Session-scoped: spin up TimescaleDB via testcontainers, run Alembic migrations once.
Function-scoped: per-test AsyncSession with transaction rollback for clean isolation.

Markers:
    unit         — pure logic, no I/O
    integration  — needs TimescaleDB container (Docker required)
    ta_validation — golden file comparison against recorded snapshots
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

# Register golden file plugin fixtures (update_golden, golden_dir)
pytest_plugins = ["tests.golden_plugin"]

_BACKEND_DIR = Path(__file__).parent.parent
_TIMESCALE_IMAGE = "timescale/timescaledb:latest-pg16"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "unit: pure logic, no I/O")
    config.addinivalue_line("markers", "integration: needs TimescaleDB container")
    config.addinivalue_line("markers", "ta_validation: golden file comparison")
    config.addinivalue_line("markers", "slow: tests taking >5s")


def _build_asyncpg_url(container: PostgresContainer) -> str:
    host = container.get_container_host_ip()
    port = container.get_exposed_port(5432)
    return (
        f"postgresql+asyncpg://{container.username}:{container.password}"
        f"@{host}:{port}/{container.dbname}"
    )


def _run_migrations(asyncpg_url: str) -> None:
    """Run Alembic migrations against the test container using a subprocess."""
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(_BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": asyncpg_url},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Alembic migration failed:\n{result.stdout}\n{result.stderr}"
        )


@pytest.fixture(scope="session")
def db_container() -> Generator[str, None, None]:
    """
    Spin up timescale/timescaledb:latest-pg16, run Alembic migrations, yield asyncpg URL.
    Container is auto-removed on teardown. Session-scoped (one container per pytest run).
    """
    with PostgresContainer(_TIMESCALE_IMAGE) as postgres:
        url = _build_asyncpg_url(postgres)
        _run_migrations(url)
        yield url


@pytest.fixture()
async def db_session(db_container: str) -> AsyncGenerator[AsyncSession, None]:
    """
    Per-test AsyncSession. Auto-begins a transaction on first use; rolls back at teardown.
    Uses async_sessionmaker so asyncpg enum type codecs are registered correctly.
    Factories should use session.flush() — not commit() — so the rollback cleans up.
    """
    engine = create_async_engine(db_container, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture()
async def async_client(db_container: str) -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    httpx.AsyncClient pointed at the FastAPI app, with the DB dependency overridden
    to use the test container instead of the production database.
    """
    from app.db.session import get_session
    from app.main import create_app

    engine = create_async_engine(db_container, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = _override_get_session

    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    await engine.dispose()
