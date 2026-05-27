"""End-to-end: migrate (via conftest testcontainer) → insert Workspace → query back."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.workspace import Workspace


@pytest.mark.asyncio
async def test_workspace_insert_and_query(session: AsyncSession) -> None:
    """Insert a workspace, flush, query back, assert fields."""
    ws = Workspace(slug="test-engine-roundtrip", name="Engine Roundtrip")
    session.add(ws)
    await session.flush()

    stmt = select(Workspace).where(Workspace.slug == "test-engine-roundtrip")
    result = await session.execute(stmt)
    fetched = result.scalar_one()

    assert fetched.id is not None
    assert len(fetched.id) == 24  # cuid2 length
    assert fetched.name == "Engine Roundtrip"
    assert fetched.region == "ap-southeast-1"
    assert fetched.created_at is not None
