"""RequirementService + TraceabilityService tests — project -> workspace scope."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from suitest_api.deps.scope import TenantContext
from suitest_api.services.requirement_service import RequirementService, TraceabilityService
from suitest_db.models.project import Project
from suitest_db.models.requirement import Requirement, RequirementLink
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


def _req() -> Requirement:
    r = Requirement(id="req_1", project_id="proj_1", public_id="REQ-1", title="Login")
    r.created_at = _NOW
    r.updated_at = _NOW
    return r


@pytest.mark.asyncio
async def test_requirement_scopes_by_workspace() -> None:
    repo = AsyncMock()
    repo.list_by_project.return_value = [_req()]
    project_repo = AsyncMock()
    project_repo.get_by_id.return_value = _project("ws_1")
    svc = RequirementService(_ctx("ws_1"), repo, project_repo)

    out = await svc.list("proj_1")

    project_repo.get_by_id.assert_awaited_once_with("proj_1")
    assert out is not None and [r.id for r in out] == ["req_1"]


@pytest.mark.asyncio
async def test_requirement_list_404_when_cross_workspace() -> None:
    repo = AsyncMock()
    project_repo = AsyncMock()
    project_repo.get_by_id.return_value = _project("ws_OTHER")
    svc = RequirementService(_ctx("ws_1"), repo, project_repo)

    assert await svc.list("proj_1") is None
    repo.list_by_project.assert_not_awaited()


@pytest.mark.asyncio
async def test_traceability_matrix_marks_coverage() -> None:
    repo = AsyncMock()
    repo.list_by_project.return_value = [_req()]
    repo.with_links.return_value = [
        RequirementLink(id="link_1", requirement_id="req_1", case_id="case_9")
    ]
    project_repo = AsyncMock()
    project_repo.get_by_id.return_value = _project("ws_1")
    svc = TraceabilityService(_ctx("ws_1"), repo, project_repo)

    matrix = await svc.matrix("proj_1")

    assert matrix is not None
    assert matrix.rows[0].covered is True
    assert matrix.rows[0].case_ids == ["case_9"]


@pytest.mark.asyncio
async def test_traceability_matrix_404_when_cross_workspace() -> None:
    repo = AsyncMock()
    project_repo = AsyncMock()
    project_repo.get_by_id.return_value = _project("ws_OTHER")
    svc = TraceabilityService(_ctx("ws_1"), repo, project_repo)

    assert await svc.matrix("proj_1") is None
