"""CapabilityService tests — ZERO base + optional workspace overlay.

LLM is configured per-workspace from the web UI (not env), so the base is always
ZERO and the materialised ``WorkspaceCapability`` overlay is what raises the tier.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from suitest_api.deps.scope import TenantContext
from suitest_api.services.capability_service import CapabilityService
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_shared.domain.enums import AutonomyLevel, Role, Tier


def _ctx(ws: str = "ws_1") -> TenantContext:
    return TenantContext(
        workspace_id=ws, user_id="00000000-0000-0000-0000-000000000001", role=Role.OWNER
    )


@pytest.mark.asyncio
async def test_capability_resolves_zero_base_when_no_overlay() -> None:
    repo = AsyncMock()
    repo.get.return_value = None
    svc = CapabilityService(_ctx("ws_1"), repo)

    out = await svc.resolve()

    repo.get.assert_awaited_once_with("ws_1")
    assert out.tier is Tier.ZERO
    assert out.overlay_applied is False
    assert out.features["ai_generation"] is False


@pytest.mark.asyncio
async def test_capability_overlay_overrides_tier() -> None:
    repo = AsyncMock()
    overlay = WorkspaceCapability(
        id="wc_1",
        workspace_id="ws_1",
        tier=Tier.CLOUD,
        autonomy_level=AutonomyLevel.ASSIST,
        features_json={"ai_generation": True},
    )
    repo.get.return_value = overlay
    svc = CapabilityService(_ctx("ws_1"), repo)

    out = await svc.resolve()

    assert out.tier is Tier.CLOUD
    assert out.overlay_applied is True
    assert out.features["ai_generation"] is True
