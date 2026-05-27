"""DB-backed endpoint test harness for the api suite.

Defined in a uniquely-named module (NOT ``conftest``) so test modules can import
``ApiDb`` for type hints without colliding with ``packages/db/tests/conftest`` on
mypy's path (two modules both named ``conftest`` are ambiguous). ``conftest.py``
imports the fixtures from here; tests import :class:`ApiDb` from here.

The ``import fastapi_users.db`` warm-up below is load-bearing: ``fastapi_users.db``
populates its SQLAlchemy base classes inside a ``try/except ImportError`` block,
and when ``suitest_db.models.user`` is the *first* module to trigger that import
(via the ``suitest_db.models`` registry barrel during collection) a partial-init
cascade swallows the names. Importing it up front — sorted into the third-party
block ahead of every ``suitest_*`` import — warms it first.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass

import fastapi_users.db as _fastapi_users_db  # noqa: F401  -- warm-up, see module docstring
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


@dataclass
class ApiDb:
    """Test harness for DB-backed endpoint tests.

    Holds the session-maker over the testcontainer and exposes ``app_for`` / ``client``
    (build an app / client with the session + current-user dependencies overridden)
    plus thin ``seed_*`` helpers. Tests consume this via the ``api_db`` fixture.
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

    async def add_all(self, rows: Sequence[Base]) -> None:
        """Persist arbitrary ORM rows (commit), for per-test fixtures."""
        async with self.maker() as session:
            session.add_all(rows)
            await session.commit()
