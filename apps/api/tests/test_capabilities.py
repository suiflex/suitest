"""Public capability contract tests."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from suitest_api.capabilities import build_base_capabilities, build_workspace_overlay
from suitest_api.main import create_app
from suitest_core.capabilities import AutonomyLevel, LlmStatus


async def _get(path: str) -> dict[str, object]:
    app = create_app()
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.get(path)
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_capabilities_default_has_no_tier_and_keeps_manual_tcm() -> None:
    data = await _get("/capabilities")
    assert "tier" not in data
    assert data["llm"] == {
        "status": "not_configured",
        "provider": None,
        "model": None,
        "base_url": None,
        "is_test_provider": False,
    }
    features = data["features"]
    assert isinstance(features, dict)
    assert features["manual_tcm"] is True
    assert features["deterministic_runner"] is False
    assert features["ai_generation"] is False


@pytest.mark.asyncio
async def test_capabilities_health_has_no_tier() -> None:
    data = await _get("/capabilities/health")
    assert data["status"] == "ok"
    assert "tier" not in data


def test_validated_workspace_llm_enables_execution() -> None:
    config = SimpleNamespace(
        provider="mock",
        model="test-model",
        config_json={},
        last_validated_at=datetime.now(UTC),
    )
    capability = SimpleNamespace(autonomy_level=AutonomyLevel.ASSIST)
    overlaid = build_workspace_overlay(
        build_base_capabilities(),
        workspace_capability=capability,  # type: ignore[arg-type]
        active_llm_config=config,  # type: ignore[arg-type]
        mcp_providers=[],
    )
    assert overlaid.llm.status is LlmStatus.READY
    assert overlaid.features.deterministic_runner is True
    assert overlaid.features.ai_generation is True
