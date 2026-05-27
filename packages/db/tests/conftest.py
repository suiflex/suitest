"""Shared DB test fixtures.

A session-scoped ``pgvector/pgvector:pg16`` testcontainer is booted once per test
session. The ``vector`` extension is created, then the full Alembic migration
chain is applied via ``alembic upgrade head`` (NOT ``metadata.create_all`` — we
want to exercise the real migrations). Each test gets a function-scoped
``AsyncSession`` whose work is rolled back at teardown so tests stay isolated.

``--import-mode=importlib`` is used project-wide, so this directory has no
``__init__.py`` (and must not get one).
"""

from __future__ import annotations

import asyncio
import base64
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import NullPool, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

_DB_PKG_ROOT = Path(__file__).resolve().parent.parent  # packages/db


@pytest.fixture(scope="session", autouse=True)
def _encryption_key() -> Iterator[None]:
    """Ensure SUITEST_ENCRYPTION_KEY is set for EncryptedBytes round-trips."""
    if not os.environ.get("SUITEST_ENCRYPTION_KEY"):
        os.environ["SUITEST_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(b"\x00" * 32).decode()
    yield


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """Boot a pgvector-enabled Postgres 16 container and yield its asyncpg URL.

    ``testcontainers`` is untyped, so the container object is kept local (never
    exposed in a fixture signature) to satisfy ``disallow_any_unimported``.
    """
    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5432)
        url = (
            f"postgresql+asyncpg://{container.username}:{container.password}"
            f"@{host}:{port}/{container.dbname}"
        )
        yield url


async def _create_vector_extension(database_url: str) -> None:
    engine = create_async_engine(database_url, future=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    await engine.dispose()


@pytest.fixture(scope="session")
def _migrated(database_url: str) -> Iterator[None]:
    """Create the vector extension and apply all migrations once per session.

    This fixture is intentionally **synchronous**: Alembic's ``env.py`` drives the
    async engine via ``asyncio.run`` internally, which cannot be nested inside the
    event loop of an async fixture. We run the extension bootstrap on a private
    loop and then invoke ``command.upgrade`` from sync context.

    ``alembic/env.py`` resolves the DB URL from ``DbSettings`` (``SUITEST_DATABASE_URL``),
    so we point that env var at the testcontainer for the duration of the upgrade —
    otherwise migrations would hit the dev/compose database instead of the container.
    """
    asyncio.run(_create_vector_extension(database_url))

    prev = os.environ.get("SUITEST_DATABASE_URL")
    os.environ["SUITEST_DATABASE_URL"] = database_url
    try:
        cfg = Config(str(_DB_PKG_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(_DB_PKG_ROOT / "alembic"))
        cfg.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(cfg, "head")
    finally:
        if prev is None:
            os.environ.pop("SUITEST_DATABASE_URL", None)
        else:
            os.environ["SUITEST_DATABASE_URL"] = prev
    yield


@pytest_asyncio.fixture
async def engine(database_url: str, _migrated: None) -> AsyncIterator[AsyncEngine]:
    """Function-scoped engine — avoids cross-event-loop reuse under asyncio strict mode."""
    eng = create_async_engine(database_url, future=True, poolclass=NullPool)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Function-scoped session; rolled back at teardown for isolation."""
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        try:
            yield s
        finally:
            await s.rollback()
