"""ProjectService scoping tests with mocked repo."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from suitest_api.deps.scope import TenantContext
from suitest_api.services.project_service import ProjectService
from suitest_db.models.project import Project
from suitest_shared.domain.enums import Role

_NOW = datetime(2026, 5, 28, tzinfo=UTC)


def _ctx(workspace_id: str = "ws_1") -> TenantContext:
    return TenantContext(
        workspace_id=workspace_id, user_id="00000000-0000-0000-0000-000000000001", role=Role.QA
    )


def _project(workspace_id: str, project_id: str = "proj_1") -> Project:
    p = Project(
        id=project_id,
        workspace_id=workspace_id,
        slug="p",
        name="P",
        description=None,
        default_mcp_routing={},
    )
    p.created_at = _NOW
    p.updated_at = _NOW
    return p


@pytest.mark.asyncio
async def test_project_scopes_by_workspace() -> None:
    repo = AsyncMock()
    repo.list_by_workspace.return_value = [_project("ws_1")]
    svc = ProjectService(_ctx("ws_1"), repo)

    out = await svc.list()

    repo.list_by_workspace.assert_awaited_once_with("ws_1")
    assert [p.id for p in out] == ["proj_1"]


@pytest.mark.asyncio
async def test_project_get_404_when_cross_workspace() -> None:
    repo = AsyncMock()
    repo.get_active_by_id.return_value = _project("ws_OTHER")
    svc = ProjectService(_ctx("ws_1"), repo)

    assert await svc.get_by_id("proj_1") is None
