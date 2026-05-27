"""McpProviderRepo tests."""

from __future__ import annotations

import pytest
from factories import make_mcp_provider, make_workspace
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.mcp_providers import McpProviderRepo


@pytest.mark.asyncio
async def test_list_paginated_two_pages(session: AsyncSession) -> None:
    repo = McpProviderRepo(session)
    ws = await make_workspace(session)
    for i in range(3):
        await make_mcp_provider(session, workspace=ws, name=f"mcp-{i}")

    first, cursor = await repo.list_paginated(cursor=None, limit=2, filters={"workspace_id": ws.id})
    assert len(first) == 2
    assert cursor is not None

    second, cursor2 = await repo.list_paginated(
        cursor=cursor, limit=2, filters={"workspace_id": ws.id}
    )
    assert len(second) == 1
    assert cursor2 is None


@pytest.mark.asyncio
async def test_list_by_workspace_and_get_by_name(session: AsyncSession) -> None:
    repo = McpProviderRepo(session)
    ws = await make_workspace(session)
    p = await make_mcp_provider(session, workspace=ws, name="playwright-mcp")

    rows = await repo.list_by_workspace(ws.id)
    assert {x.id for x in rows} == {p.id}

    found = await repo.get_by_name(ws.id, "playwright-mcp")
    assert found is not None and found.id == p.id
    assert await repo.get_by_name(ws.id, "absent") is None
