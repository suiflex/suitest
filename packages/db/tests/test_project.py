"""Tests for projects + suites (Task 2b)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.ids import new_id
from suitest_db.models.project import Project, Suite
from suitest_db.models.workspace import Workspace


async def _workspace(session: AsyncSession) -> Workspace:
    ws = Workspace(slug=f"ws-{new_id()}", name="WS")
    session.add(ws)
    await session.flush()
    return ws


@pytest.mark.asyncio
async def test_project_unique_slug_per_workspace(session: AsyncSession) -> None:
    ws = await _workspace(session)
    session.add(Project(workspace_id=ws.id, slug="x", name="P1"))
    await session.flush()
    session.add(Project(workspace_id=ws.id, slug="x", name="P2"))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_project_slug_can_repeat_across_workspaces(session: AsyncSession) -> None:
    ws1 = await _workspace(session)
    ws2 = await _workspace(session)
    session.add(Project(workspace_id=ws1.id, slug="shared", name="P1"))
    session.add(Project(workspace_id=ws2.id, slug="shared", name="P2"))
    await session.flush()  # no error


@pytest.mark.asyncio
async def test_suite_cascade_on_project_delete(session: AsyncSession) -> None:
    ws = await _workspace(session)
    project = Project(workspace_id=ws.id, slug=f"p-{new_id()}", name="P")
    session.add(project)
    await session.flush()
    suite = Suite(project_id=project.id, name="S")
    session.add(suite)
    await session.flush()
    sid = suite.id

    await session.delete(project)
    await session.flush()
    assert await session.get(Suite, sid) is None


@pytest.mark.asyncio
async def test_suite_order_default_zero(session: AsyncSession) -> None:
    ws = await _workspace(session)
    project = Project(workspace_id=ws.id, slug=f"p-{new_id()}", name="P")
    session.add(project)
    await session.flush()
    suite = Suite(project_id=project.id, name="S")
    session.add(suite)
    await session.flush()
    fetched = await session.scalar(select(Suite).where(Suite.id == suite.id))
    assert fetched is not None
    assert fetched.order == 0
