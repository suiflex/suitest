"""Shared fixtures for the api test suite.

Two flavours:

* ``client`` — a lifespan-wired ASGI client with NO database (used by the
  capability / health / auth contract tests that never touch the DB).
* ``api_db`` — a Postgres (pgvector) testcontainer with the Alembic chain applied
  once per session, exposing a session-maker plus ``app_for`` / ``client``
  helpers that override ``get_async_session`` + ``current_active_user`` so the
  Task 7 read endpoints can be driven end-to-end against a real DB with a seeded,
  authenticated user, alongside thin ``seed_*`` helpers.
"""

from __future__ import annotations

import asyncio
import base64
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import fastapi_users.db as _fastapi_users_db  # noqa: F401  -- warm-up, see below
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from suitest_api.auth.db import get_async_session
from suitest_api.auth.manager import current_active_user
from suitest_api.main import create_app
from suitest_db.base import Base
from suitest_db.models.tenancy import Membership
from suitest_db.models.user import User
from suitest_db.models.workspace import Workspace
from suitest_shared.domain.enums import Role

# NOTE on the bare ``import fastapi_users.db`` above: ``fastapi_users.db`` populates
# its SQLAlchemy base classes inside a ``try/except ImportError`` block. When
# ``suitest_db.models.user`` is the *first* module to trigger that import (which
# happens via the ``suitest_db.models`` registry barrel during pytest collection),
# a partial-init cascade makes the inner import raise and get silently swallowed,
# leaving the names absent. Importing ``fastapi_users.db`` up front — sorted into
# the third-party block ahead of every ``suitest_*`` import — warms it first.

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DB_PKG_ROOT = _REPO_ROOT / "packages" / "db"


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Return an httpx AsyncClient wired to the ASGI app via lifespan (no DB)."""
    app = create_app()
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@dataclass
class ApiDb:
    """Test harness for DB-backed endpoint tests.

    Holds the session-maker over the testcontainer and exposes ``app_for`` (build
    an app with the session + current-user dependencies overridden) plus thin
    ``seed_*`` helpers. Tests consume this via the ``api_db`` fixture only — no
    cross-module import is needed, which keeps ``--import-mode=importlib`` happy
    (there is no ``tests/__init__.py``).
    """

    maker: async_sessionmaker[AsyncSession]

    def app_for(self, user: User | None) -> FastAPI:
        """Build an app overriding the session + (optionally) the current user.

        Passing ``user=None`` leaves ``current_active_user`` un-overridden so the
        real FastAPI-Users dependency runs and unauthenticated requests get 401.
        """
        app = create_app()

        async def _override_session() -> AsyncIterator[AsyncSession]:
            async with self.maker() as session:
                yield session

        app.dependency_overrides[get_async_session] = _override_session
        if user is not None:
            app.dependency_overrides[current_active_user] = lambda: user
        return app

    @asynccontextmanager
    async def client(self, user: User | None) -> AsyncIterator[AsyncClient]:
        """Yield a lifespan-wired httpx client bound to ``app_for(user)``."""
        app = self.app_for(user)
        async with LifespanManager(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                yield c

    async def seed_user(self, *, email: str, name: str = "Test User") -> User:
        """Insert a User row and return it (detached; usable as an auth override)."""
        async with self.maker() as session:
            user = User(
                id=uuid.uuid4(),
                email=email,
                hashed_password="x",  # test fixture placeholder, not a real credential
                is_active=True,
                is_superuser=False,
                is_verified=True,
                name=name,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user

    async def seed_workspace(self, *, slug: str, name: str) -> Workspace:
        """Insert a Workspace row and return it (detached)."""
        async with self.maker() as session:
            ws = Workspace(slug=slug, name=name)
            session.add(ws)
            await session.commit()
            await session.refresh(ws)
        return ws

    async def seed_membership(
        self, *, workspace_id: str, user_id: uuid.UUID, role: Role = Role.QA
    ) -> None:
        """Insert a Membership linking ``user_id`` to ``workspace_id``."""
        async with self.maker() as session:
            session.add(Membership(workspace_id=workspace_id, user_id=user_id, role=role))
            await session.commit()

    async def member_workspace(
        self, user: User, *, slug: str, name: str | None = None
    ) -> Workspace:
        """Create a workspace + a membership for ``user`` in one call."""
        ws = await self.seed_workspace(slug=slug, name=name or slug)
        await self.seed_membership(workspace_id=ws.id, user_id=user.id)
        return ws

    async def add_all(self, rows: list[Base]) -> None:
        """Persist arbitrary ORM rows (commit), for per-test fixtures."""
        async with self.maker() as session:
            session.add_all(rows)
            await session.commit()


@pytest.fixture(scope="session")
def _database_url() -> Iterator[str]:
    """Boot a pgvector Postgres container and apply the Alembic chain once."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from testcontainers.postgres import PostgresContainer

    if not os.environ.get("SUITEST_ENCRYPTION_KEY"):
        os.environ["SUITEST_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(b"\x00" * 32).decode()

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
        yield url


@pytest_asyncio.fixture
async def api_db(_database_url: str) -> AsyncIterator[ApiDb]:
    """Yield an :class:`ApiDb` bound to a fresh engine over the container."""
    from sqlalchemy import NullPool
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_database_url, future=True, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield ApiDb(maker=maker)
    finally:
        await engine.dispose()
