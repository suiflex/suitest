"""DefectService tests — direct workspace_id scoping."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from suitest_api.deps.scope import TenantContext
from suitest_api.services.defect_service import DefectService
from suitest_db.models.defect import Defect
from suitest_shared.domain.enums import DefectStatus, DiagnosisKind, Role, Severity

_NOW = datetime(2026, 5, 28, tzinfo=UTC)


def _ctx(ws: str = "ws_1") -> TenantContext:
    return TenantContext(
        workspace_id=ws, user_id="00000000-0000-0000-0000-000000000001", role=Role.QA
    )


def _defect(ws: str) -> Defect:
    d = Defect(
        id="def_1",
        public_id="BUG-1",
        workspace_id=ws,
        title="boom",
        severity=Severity.HIGH,
        status=DefectStatus.OPEN,
        created_by="tester",
        agent_diagnosis_kind=DiagnosisKind.MANUAL_TRIAGE,
    )
    d.created_at = _NOW
    d.updated_at = _NOW
    return d


@pytest.mark.asyncio
async def test_defect_scopes_by_workspace() -> None:
    repo = AsyncMock()
    repo.list_by_workspace.return_value = ([_defect("ws_1")], None)
    svc = DefectService(_ctx("ws_1"), repo)

    out = await svc.list()

    assert repo.list_by_workspace.await_args.args[0] == "ws_1"
    assert [d.id for d in out] == ["def_1"]


@pytest.mark.asyncio
async def test_defect_get_404_when_cross_workspace() -> None:
    repo = AsyncMock()
    repo.get_by_id.return_value = _defect("ws_OTHER")
    svc = DefectService(_ctx("ws_1"), repo)

    assert await svc.get_by_id("def_1") is None
