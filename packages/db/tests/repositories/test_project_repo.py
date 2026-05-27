"""ProjectRepo tests."""

from __future__ import annotations

import pytest
from factories import make_project, make_workspace
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.projects import ProjectRepo


@pytest.mark.asyncio
async def test_list_paginated_two_pages(session: AsyncSession) -> None:
    repo = ProjectRepo(session)
    ws = await make_workspace(session)
    for _ in range(3):
        await make_project(session, workspace=ws)

    first, cursor = await repo.list_paginated(cursor=None, limit=2, filters={"workspace_id": ws.id})
    assert len(first) == 2
    assert cursor is not None

    second, cursor2 = await repo.list_paginated(
        cursor=cursor, limit=2, filters={"workspace_id": ws.id}
    )
    assert len(second) == 1
    assert cursor2 is None


@pytest.mark.asyncio
async def test_list_by_workspace_and_get_by_slug(session: AsyncSession) -> None:
    repo = ProjectRepo(session)
    ws = await make_workspace(session)
    other = await make_workspace(session)
    p1 = await make_project(session, workspace=ws)
    await make_project(session, workspace=other)

    rows = await repo.list_by_workspace(ws.id)
    assert {p.id for p in rows} == {p1.id}

    found = await repo.get_by_slug(ws.id, p1.slug)
    assert found is not None and found.id == p1.id
    assert await repo.get_by_slug(other.id, p1.slug) is None
