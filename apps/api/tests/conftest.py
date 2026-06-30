"""Shared fixtures for the api test suite.

Two flavours:

* ``client`` — a lifespan-wired ASGI client with NO database (used by the
  capability / health / auth contract tests that never touch the DB).
* ``api_db`` — a Postgres (pgvector) testcontainer with the Alembic chain applied
  once per session, yielding an :class:`~api_harness.ApiDb` whose ``app_for`` /
  ``client`` helpers override ``get_async_session`` + ``current_active_user`` so the
  Task 7 read endpoints can be driven end-to-end against a real DB. The harness
  class lives in ``api_harness`` (not here) so tests can import it for type hints
  without a ``conftest`` module-name collision on mypy's path.
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

# Disable OpenTelemetry exporter by default in tests — the BatchSpanProcessor
# would otherwise spin up a background thread trying to flush to localhost:4318
# (no collector in CI). Individual observability tests can opt back in by clearing
# this env var before constructing the app.
os.environ.setdefault("SUITEST_OTEL_DISABLED", "true")

# Make ``api_harness`` (this directory) importable under --import-mode=importlib,
# which does NOT add test dirs to sys.path. Done before the import below.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
import pytest_asyncio
from api_harness import ApiDb
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from suitest_api.main import create_app

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DB_PKG_ROOT = _REPO_ROOT / "packages" / "db"


@pytest.fixture(autouse=True)
def _disable_app_bootstrap(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep API app tests on fixture-owned DB sessions and ZERO defaults.

    The developer `.env` enables first-install super-admin bootstrap for real
    app boots. Endpoint tests create many lifespan-wired apps under
    pytest-asyncio's function-scoped loops; letting those apps use the global
    production sessionmaker leaks asyncpg connections across loops.
    """
    monkeypatch.setenv("SUITEST_SUPERADMIN_EMAIL", "")
    monkeypatch.setenv("SUITEST_SUPERADMIN_PASSWORD", "")
    for var in (
        "SUITEST_LLM_PROVIDER",
        "SUITEST_LLM_BASE_URL",
        "SUITEST_LLM_API_KEY",
        "SUITEST_LLM_MODEL",
        "SUITEST_EMBEDDINGS_BACKEND",
        "SUITEST_EMBEDDINGS_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Return an httpx AsyncClient wired to the ASGI app via lifespan (no DB)."""
    app = create_app()
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture(scope="session")
def _database_url() -> Iterator[str]:
    """Provide a pgvector Postgres URL with the Alembic chain applied once.

    Two modes:

    * If ``SUITEST_DATABASE_URL`` is set, run against that external,
      pre-provisioned database (no Docker required). Point it at a DEDICATED
      throwaway database — the ``api_db`` fixture TRUNCATEs every table per test,
      so it must never be a database holding real data.
    * Otherwise boot a disposable ``pgvector/pgvector:pg16`` testcontainer.
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    if not os.environ.get("SUITEST_ENCRYPTION_KEY"):
        os.environ["SUITEST_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(b"\x00" * 32).decode()

    def _migrate(url: str) -> None:
        prev = os.environ.get("SUITEST_DATABASE_URL")
        os.environ["SUITEST_DATABASE_URL"] = url
        try:
            cfg = Config(str(_DB_PKG_ROOT / "alembic.ini"))
            cfg.set_main_option("script_location", str(_DB_PKG_ROOT / "alembic"))
            cfg.set_main_option("sqlalchemy.url", url)
            command.upgrade(cfg, "head")
        finally:
            if prev is None:
                os.environ.pop("SUITEST_DATABASE_URL", None)
            else:
                os.environ["SUITEST_DATABASE_URL"] = prev

    external = os.environ.get("SUITEST_DATABASE_URL")
    if external:

        async def _bootstrap_external() -> None:
            engine = create_async_engine(external, future=True)
            async with engine.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await engine.dispose()

        asyncio.run(_bootstrap_external())
        _migrate(external)
        yield external
        return

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5432)
        url = (
            f"postgresql+asyncpg://{container.username}:{container.password}"
            f"@{host}:{port}/{container.dbname}"
        )

        async def _bootstrap() -> None:
            engine = create_async_engine(url, future=True)
            async with engine.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await engine.dispose()

        asyncio.run(_bootstrap())
        _migrate(url)
        yield url


@pytest_asyncio.fixture
async def api_db(_database_url: str) -> AsyncIterator[ApiDb]:
    """Yield an :class:`ApiDb` bound to a fresh engine over the container.

    Truncates every table (except the Alembic version bookkeeping) up front so each
    test starts from an empty DB — the testcontainer + schema are reused across the
    whole session, but per-test data is isolated, which keeps globally-unique
    columns like ``test_cases.public_id`` from colliding across tests.
    """
    from sqlalchemy import NullPool, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from suitest_db.base import Base

    engine = create_async_engine(_database_url, future=True, poolclass=NullPool)
    table_names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield ApiDb(maker=maker)
    finally:
        await engine.dispose()
