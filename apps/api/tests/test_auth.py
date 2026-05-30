"""Auth router contract tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_users_me_unauthenticated_returns_401(client: AsyncClient) -> None:
    """GET /users/me without auth cookie must return 401."""
    response = await client.get("/users/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_google_authorize_returns_redirect(client: AsyncClient) -> None:
    """GET /auth/google/authorize returns a Google authorization URL."""
    response = await client.get("/auth/google/authorize")
    assert response.status_code == 200
    payload = response.json()
    assert "authorization_url" in payload
    assert "accounts.google.com" in payload["authorization_url"]


@pytest.mark.asyncio
async def test_public_register_is_disabled(client: AsyncClient) -> None:
    """M1e is invite-only; public self-registration must not be mounted."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "new@example.com",
            "password": "secret123",
            "name": "New User",
        },
    )
    assert response.status_code == 404
