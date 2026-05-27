"""IntegrationRepo tests."""

from __future__ import annotations

import pytest
from factories import make_integration, make_workspace
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.integrations import IntegrationRepo
from suitest_shared.domain.enums import IntegrationKind


@pytest.mark.asyncio
async def test_list_paginated_two_pages(session: AsyncSession) -> None:
    repo = IntegrationRepo(session)
    ws = await make_workspace(session)
    for _ in range(3):
        await make_integration(session, workspace=ws)

    first, cursor = await repo.list_paginated(cursor=None, limit=2, filters={"workspace_id": ws.id})
    assert len(first) == 2
    assert cursor is not None

    second, cursor2 = await repo.list_paginated(
        cursor=cursor, limit=2, filters={"workspace_id": ws.id}
    )
    assert len(second) == 1
    assert cursor2 is None


@pytest.mark.asyncio
async def test_list_by_workspace_kind(session: AsyncSession) -> None:
    repo = IntegrationRepo(session)
    ws = await make_workspace(session)
    gh = await make_integration(session, workspace=ws, kind=IntegrationKind.GITHUB)
    await make_integration(session, workspace=ws, kind=IntegrationKind.SLACK)

    rows = await repo.list_by_workspace(ws.id, kind=IntegrationKind.GITHUB)
    assert {i.id for i in rows} == {gh.id}
    all_rows = await repo.list_by_workspace(ws.id)
    assert len(all_rows) == 2
