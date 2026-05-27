"""WorkspaceRepo tests."""

from __future__ import annotations

import pytest
from factories import make_membership, make_user, make_workspace
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.workspaces import WorkspaceRepo


@pytest.mark.asyncio
async def test_list_paginated_two_pages(session: AsyncSession) -> None:
    repo = WorkspaceRepo(session)
    for _ in range(3):
        await make_workspace(session)

    first, cursor = await repo.list_paginated(cursor=None, limit=2)
    assert len(first) == 2
    assert cursor is not None

    second, cursor2 = await repo.list_paginated(cursor=cursor, limit=2)
    assert len(second) == 1
    assert cursor2 is None

    seen = {w.id for w in (*first, *second)}
    assert len(seen) == 3


@pytest.mark.asyncio
async def test_list_for_user(session: AsyncSession) -> None:
    repo = WorkspaceRepo(session)
    user = await make_user(session)
    ws1 = await make_workspace(session)
    ws2 = await make_workspace(session)
    await make_workspace(session)  # user is NOT a member
    await make_membership(session, workspace=ws1, user=user)
    await make_membership(session, workspace=ws2, user=user)

    rows = await repo.list_for_user(user.id)
    assert {w.id for w in rows} == {ws1.id, ws2.id}


@pytest.mark.asyncio
async def test_get_by_slug(session: AsyncSession) -> None:
    repo = WorkspaceRepo(session)
    ws = await make_workspace(session)
    found = await repo.get_by_slug(ws.slug)
    assert found is not None
    assert found.id == ws.id
    assert await repo.get_by_slug("nonexistent") is None
