"""LLMConfigRepo tests."""

from __future__ import annotations

import pytest
from factories import make_llm_config, make_workspace
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.llm_configs import LLMConfigRepo


@pytest.mark.asyncio
async def test_list_paginated_two_pages(session: AsyncSession) -> None:
    repo = LLMConfigRepo(session)
    ws = await make_workspace(session)
    for _ in range(3):
        await make_llm_config(session, workspace=ws)

    first, cursor = await repo.list_paginated(cursor=None, limit=2, filters={"workspace_id": ws.id})
    assert len(first) == 2
    assert cursor is not None

    second, cursor2 = await repo.list_paginated(
        cursor=cursor, limit=2, filters={"workspace_id": ws.id}
    )
    assert len(second) == 1
    assert cursor2 is None


@pytest.mark.asyncio
async def test_get_active(session: AsyncSession) -> None:
    repo = LLMConfigRepo(session)
    ws = await make_workspace(session)
    await make_llm_config(session, workspace=ws, is_active=False)
    active = await make_llm_config(session, workspace=ws, is_active=True)

    found = await repo.get_active(ws.id)
    assert found is not None
    assert found.id == active.id
