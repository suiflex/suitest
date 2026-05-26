"""End-to-end: migrate → insert Workspace → query back."""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.engine import lifespan_engine
from suitest_db.models import Workspace
from suitest_db.settings import DbSettings


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Yield a session against local dev Postgres (after compose up + alembic upgrade)."""
    settings = DbSettings(
        database_url="postgresql+asyncpg://suitest:suitest@localhost:5432/suitest"
    )
    async with lifespan_engine(settings) as (_engine, sf), sf() as s:
        yield s
        await s.rollback()


@pytest.mark.asyncio
async def test_workspace_insert_and_query(session: AsyncSession) -> None:
    """Insert a workspace, commit, query back, assert fields."""
    ws = Workspace(slug="test-engine-roundtrip", name="Engine Roundtrip")
    session.add(ws)
    await session.commit()

    stmt = select(Workspace).where(Workspace.slug == "test-engine-roundtrip")
    result = await session.execute(stmt)
    fetched = result.scalar_one()

    assert fetched.id is not None
    assert len(fetched.id) == 24  # cuid2 length
    assert fetched.name == "Engine Roundtrip"
    assert fetched.created_at is not None

    # cleanup
    await session.delete(fetched)
    await session.commit()
