"""Tests for requirements + traceability links (Task 2d)."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.ids import new_id
from suitest_db.models.case import TestCase
from suitest_db.models.project import Project, Suite
from suitest_db.models.requirement import Requirement, RequirementLink
from suitest_db.models.workspace import Workspace
from suitest_shared.domain.enums import CaseSource


async def _project_with_case(session: AsyncSession) -> tuple[Project, TestCase]:
    ws = Workspace(slug=f"ws-{new_id()}", name="WS")
    session.add(ws)
    await session.flush()
    project = Project(workspace_id=ws.id, slug=f"p-{new_id()}", name="P")
    session.add(project)
    await session.flush()
    suite = Suite(project_id=project.id, name="S")
    session.add(suite)
    await session.flush()
    case = TestCase(
        suite_id=suite.id, public_id=f"TC-{new_id()}", name="C", source=CaseSource.MANUAL
    )
    session.add(case)
    await session.flush()
    return project, case


async def _requirement(session: AsyncSession, project: Project) -> Requirement:
    req = Requirement(project_id=project.id, public_id=f"REQ-{new_id()}", title="Req")
    session.add(req)
    await session.flush()
    return req


@pytest.mark.asyncio
async def test_requirement_link_unique(session: AsyncSession) -> None:
    project, case = await _project_with_case(session)
    req = await _requirement(session, project)
    session.add(RequirementLink(requirement_id=req.id, case_id=case.id))
    await session.flush()
    session.add(RequirementLink(requirement_id=req.id, case_id=case.id))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_requirement_link_cascade_delete_via_case(session: AsyncSession) -> None:
    project, case = await _project_with_case(session)
    req = await _requirement(session, project)
    link = RequirementLink(requirement_id=req.id, case_id=case.id)
    session.add(link)
    await session.flush()
    lid = link.id

    await session.delete(case)
    await session.flush()
    session.expunge_all()
    assert await session.get(RequirementLink, lid) is None
    assert await session.get(Requirement, req.id) is not None


@pytest.mark.asyncio
async def test_requirement_link_cascade_delete_via_requirement(session: AsyncSession) -> None:
    project, case = await _project_with_case(session)
    req = await _requirement(session, project)
    link = RequirementLink(requirement_id=req.id, case_id=case.id)
    session.add(link)
    await session.flush()
    lid = link.id

    await session.delete(req)
    await session.flush()
    session.expunge_all()
    assert await session.get(RequirementLink, lid) is None
    assert await session.get(TestCase, case.id) is not None
