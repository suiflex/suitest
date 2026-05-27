"""SuiteRepo tests."""

from __future__ import annotations

import pytest
from factories import make_project, make_suite, make_workspace
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.suites import SuiteRepo


@pytest.mark.asyncio
async def test_list_paginated_two_pages(session: AsyncSession) -> None:
    repo = SuiteRepo(session)
    ws = await make_workspace(session)
    project = await make_project(session, workspace=ws)
    for _ in range(3):
        await make_suite(session, project=project)

    first, cursor = await repo.list_paginated(
        cursor=None, limit=2, filters={"project_id": project.id}
    )
    assert len(first) == 2
    assert cursor is not None

    second, cursor2 = await repo.list_paginated(
        cursor=cursor, limit=2, filters={"project_id": project.id}
    )
    assert len(second) == 1
    assert cursor2 is None


@pytest.mark.asyncio
async def test_list_by_project(session: AsyncSession) -> None:
    repo = SuiteRepo(session)
    ws = await make_workspace(session)
    project = await make_project(session, workspace=ws)
    other = await make_project(session, workspace=ws)
    s1 = await make_suite(session, project=project)
    await make_suite(session, project=other)

    rows = await repo.list_by_project(project.id)
    assert {s.id for s in rows} == {s1.id}
