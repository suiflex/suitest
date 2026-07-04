"""TestCaseService tests — scoped via suite -> project -> workspace."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from suitest_api.deps.scope import TenantContext
from suitest_api.services.test_case_service import TestCaseService
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.project import Project, Suite
from suitest_shared.domain.enums import CaseSource, CaseStatus, Priority, Role, TargetKind

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


def _case() -> TestCase:
    c = TestCase(
        id="case_1",
        suite_id="suite_1",
        public_id="TC-1",
        name="C",
        title="C",
        source=CaseSource.MANUAL,
        status=CaseStatus.ACTIVE,
        priority=Priority.P2,
    )
    c.created_at = _NOW
    c.updated_at = _NOW
    return c


def _step() -> TestStep:
    return TestStep(
        id="step_1",
        case_id="case_1",
        order=1,
        action="click",
        expected="ok",
        mcp_provider="playwright-mcp",
        target_kind=TargetKind.FE_WEB,
    )


def _scoped_repos(ws_for_project: str) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
    repo = AsyncMock()
    suite_repo = AsyncMock()
    project_repo = AsyncMock()
    suite_repo.get_by_id.return_value = _suite()
    project_repo.get_by_id.return_value = _project(ws_for_project)
    return repo, suite_repo, project_repo


@pytest.mark.asyncio
async def test_test_case_scopes_by_workspace() -> None:
    repo, suite_repo, project_repo = _scoped_repos("ws_1")
    repo.list_by_suite_filtered.return_value = ([_case()], None)
    svc = TestCaseService(_ctx("ws_1"), repo, suite_repo, project_repo)

    out = await svc.list("suite_1")

    suite_repo.get_by_id.assert_awaited_once_with("suite_1")
    repo.list_by_suite_filtered.assert_awaited_once()
    assert out is not None and [c.id for c in out] == ["case_1"]


@pytest.mark.asyncio
async def test_test_case_list_404_when_cross_workspace() -> None:
    repo, suite_repo, project_repo = _scoped_repos("ws_OTHER")
    svc = TestCaseService(_ctx("ws_1"), repo, suite_repo, project_repo)

    assert await svc.list("suite_1") is None
    repo.list_by_suite_filtered.assert_not_awaited()


@pytest.mark.asyncio
async def test_test_case_get_with_steps_in_scope() -> None:
    repo, suite_repo, project_repo = _scoped_repos("ws_1")
    repo.get_by_id.return_value = _case()
    repo.get_steps.return_value = [_step()]
    svc = TestCaseService(_ctx("ws_1"), repo, suite_repo, project_repo)

    out = await svc.get_by_id_with_steps("case_1")

    assert out is not None
    assert out.id == "case_1"
    assert [s.id for s in out.steps] == ["step_1"]


@pytest.mark.asyncio
async def test_test_case_get_404_when_cross_workspace() -> None:
    repo, suite_repo, project_repo = _scoped_repos("ws_OTHER")
    repo.get_by_id.return_value = _case()
    svc = TestCaseService(_ctx("ws_1"), repo, suite_repo, project_repo)

    assert await svc.get_by_id_with_steps("case_1") is None
    repo.get_steps.assert_not_awaited()
