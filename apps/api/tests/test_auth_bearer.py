"""Bearer JWT authentication contract tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_api.auth.manager import get_jwt_strategy

if TYPE_CHECKING:
    from api_harness import ApiDb


@pytest.mark.asyncio
async def test_auth_me_accepts_authorization_bearer_jwt(api_db: ApiDb) -> None:
    """A FastAPI-Users JWT in the Authorization header authenticates web/API calls."""
    user = await api_db.seed_user(email="bearer-user@suitest.local", name="Bearer User")
    workspace = await api_db.member_workspace(user, slug="bearer-ws", name="Bearer Workspace")
    token = await get_jwt_strategy().write_token(user)

    async with api_db.client(None) as client:
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == "bearer-user@suitest.local"
    assert body["memberships"][0]["workspace"]["slug"] == "bearer-ws"
