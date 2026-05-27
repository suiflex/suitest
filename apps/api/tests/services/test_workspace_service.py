"""WorkspaceService tests (not workspace-scoped — membership-scoped)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from suitest_api.deps.scope import TenantContext
from suitest_api.services.workspace_service import WorkspaceService
from suitest_db.models.workspace import Workspace
from suitest_shared.domain.enums import Role

_NOW = datetime(2026, 5, 28, tzinfo=UTC)
_USER_ID = "00000000-0000-0000-0000-000000000001"


def _ctx() -> TenantContext:
    return TenantContext(workspace_id="ws_1", user_id=_USER_ID, role=Role.OWNER)


def _ws(ws_id: str) -> Workspace:
    w = Workspace(id=ws_id, slug=ws_id, name=ws_id, region="ap-southeast-1")
    w.created_at = _NOW
    w.updated_at = _NOW
    return w


@pytest.mark.asyncio
async def test_workspace_list_for_user_passes_user_id() -> None:
    repo = AsyncMock()
    repo.list_for_user.return_value = [_ws("ws_1"), _ws("ws_2")]
    svc = WorkspaceService(_ctx(), repo)

    out = await svc.list_for_user()

    repo.list_for_user.assert_awaited_once_with(uuid.UUID(_USER_ID))
    assert {w.id for w in out} == {"ws_1", "ws_2"}


@pytest.mark.asyncio
async def test_workspace_get_404_when_not_a_member() -> None:
    repo = AsyncMock()
    repo.list_for_user.return_value = [_ws("ws_1")]
    svc = WorkspaceService(_ctx(), repo)

    assert await svc.get_by_id_for_user("ws_NOT_MINE") is None
    assert (await svc.get_by_id_for_user("ws_1")).id == "ws_1"  # type: ignore[union-attr]
