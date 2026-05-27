"""SuiteService tests — scoped via parent project's workspace."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from suitest_api.deps.scope import TenantContext
from suitest_api.services.suite_service import SuiteService
from suitest_db.models.project import Project, Suite
from suitest_shared.domain.enums import Role

_NOW = datetime(2026, 5, 28, tzinfo=UTC)


def _ctx(ws: str = "ws_1") -> TenantContext:
    return TenantContext(
        workspace_id=ws, user_id="00000000-0000-0000-0000-000000000001", role=Role.QA
    )


def _project(ws: str) -> Project:
    p = Project(id="proj_1", workspace_id=ws, slug="p", name="P")
    p.created_at = _NOW
    p.updated_at = _NOW
    return p


def _suite() -> Suite:
    s = Suite(id="suite_1", project_id="proj_1", name="S", order=0)
    s.created_at = _NOW
    s.updated_at = _NOW
    return s


@pytest.mark.asyncio
async def test_suite_scopes_by_workspace() -> None:
    repo = AsyncMock()
    repo.list_by_project.return_value = [_suite()]
    project_repo = AsyncMock()
    project_repo.get_by_id.return_value = _project("ws_1")
    svc = SuiteService(_ctx("ws_1"), repo, project_repo)

    out = await svc.list("proj_1")

    project_repo.get_by_id.assert_awaited_once_with("proj_1")
    repo.list_by_project.assert_awaited_once_with("proj_1")
    assert out is not None and [s.id for s in out] == ["suite_1"]


@pytest.mark.asyncio
async def test_suite_list_404_when_cross_workspace() -> None:
    repo = AsyncMock()
    project_repo = AsyncMock()
    project_repo.get_by_id.return_value = _project("ws_OTHER")
    svc = SuiteService(_ctx("ws_1"), repo, project_repo)

    assert await svc.list("proj_1") is None
    repo.list_by_project.assert_not_awaited()


@pytest.mark.asyncio
async def test_suite_get_404_when_cross_workspace() -> None:
    repo = AsyncMock()
    repo.get_by_id.return_value = _suite()
    project_repo = AsyncMock()
    project_repo.get_by_id.return_value = _project("ws_OTHER")
    svc = SuiteService(_ctx("ws_1"), repo, project_repo)

    assert await svc.get_by_id("suite_1") is None
