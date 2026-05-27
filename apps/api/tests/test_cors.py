"""CORS middleware contract test."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_cors_allows_web_origin(client: AsyncClient) -> None:
    """Preflight/simple request from web origin gets ACAO header."""
    response = await client.get(
        "/capabilities",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") == "true"
