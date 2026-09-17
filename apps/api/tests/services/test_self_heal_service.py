from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from suitest_agent.generators.selector_repair import selector_code_sha256
from suitest_api.schemas.self_heal import SelectorRepairApplyRequest
from suitest_api.services.self_heal_service import SelfHealError, SelfHealService
from suitest_db.models.case import TestStep
from suitest_shared.domain.enums import AutonomyLevel, TargetKind


def _step() -> TestStep:
    return TestStep(
        id="step-1",
        case_id="case-1",
        order=1,
        action="Click save",
        expected="Saved",
        code=json.dumps({"tool": "browser_click", "arguments": {"selector": "#submit"}}),
        mcp_provider="playwright-mcp",
        target_kind=TargetKind.FE_WEB,
    )


@pytest.mark.asyncio
async def test_apply_requires_non_manual_autonomy_and_rejects_stale_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    service = SelfHealService(session, workspace_id="ws-1", user_id=None)
    step = _step()
    monkeypatch.setattr(service, "_step", AsyncMock(return_value=step))

    capability = AsyncMock()
    capability.autonomy_level = AutonomyLevel.MANUAL

    class _Caps:
        def __init__(self, _session: object) -> None:
            pass

        async def get(self, _workspace_id: str) -> object:
            return capability

    monkeypatch.setattr(
        "suitest_api.services.self_heal_service.WorkspaceCapabilityRepo",
        _Caps,
    )
    request = SelectorRepairApplyRequest(
        step_id=step.id,
        old_selector="#submit",
        new_selector="[data-testid=save]",
        code_sha256=selector_code_sha256(step.code or ""),
    )
    with pytest.raises(SelfHealError, match="requires assist"):
        await service.apply("case-1", request)

    capability.autonomy_level = AutonomyLevel.ASSIST
    stale = request.model_copy(update={"code_sha256": "0" * 64})
    with pytest.raises(SelfHealError, match="changed after"):
        await service.apply("case-1", stale)
