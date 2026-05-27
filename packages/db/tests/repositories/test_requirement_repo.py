"""RequirementRepo tests."""

from __future__ import annotations

import pytest
from factories import make_project, make_requirement, make_suite, make_test_case, make_workspace
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.requirement import RequirementLink
from suitest_db.repositories.requirements import RequirementRepo


@pytest.mark.asyncio
async def test_list_paginated_two_pages(session: AsyncSession) -> None:
    repo = RequirementRepo(session)
    ws = await make_workspace(session)
    project = await make_project(session, workspace=ws)
    for _ in range(3):
        await make_requirement(session, project=project)

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
async def test_with_links(session: AsyncSession) -> None:
    repo = RequirementRepo(session)
    ws = await make_workspace(session)
    project = await make_project(session, workspace=ws)
    suite = await make_suite(session, project=project)
    req = await make_requirement(session, project=project)
    case = await make_test_case(session, suite=suite)
    session.add(RequirementLink(requirement_id=req.id, case_id=case.id))
    await session.flush()

    links = await repo.with_links(req.id)
    assert len(links) == 1
    assert links[0].case_id == case.id
