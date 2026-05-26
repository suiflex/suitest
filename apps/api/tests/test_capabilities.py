"""Contract test for the /capabilities endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_capabilities_zero_default(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unset SUITEST_LLM_PROVIDER → ZERO tier capabilities response."""
    monkeypatch.delenv("SUITEST_LLM_PROVIDER", raising=False)
    response = await client.get("/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert data["tier"] == "ZERO"
    assert data["llm_provider"] is None
    assert data["features"]["manual_tcm"] is True
    assert data["features"]["ai_generation"] is False
    assert data["autonomy"]["default"] == "manual"
    assert data["autonomy"]["available"] == ["manual"]
