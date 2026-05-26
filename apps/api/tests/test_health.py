"""Health endpoint contract tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient) -> None:
    """GET /health returns 200 + canonical payload."""
    response = await client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload == {"status": "ok", "service": "api", "version": "0.1.0"}
