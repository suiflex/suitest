"""M1e invitation endpoint tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from api_harness import ApiDb
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from suitest_api.auth.db import get_async_session
from suitest_api.auth.manager import current_active_user
from suitest_api.main import create_app
from suitest_db.models.tenancy import Membership
from suitest_db.models.user import User
from suitest_shared.domain.enums import Role


async def _client_for(api_db: ApiDb, user: User | None) -> AsyncClient:
    app = create_app()

    async def _override_session() -> AsyncIterator[object]:
        async with api_db.maker() as session:
            yield session

    async def _override_current_user() -> User:
        assert user is not None
        async with api_db.maker() as session:
            db_user = await session.get(User, user.id)
            assert db_user is not None
            return db_user

    app.dependency_overrides[get_async_session] = _override_session
    if user is not None:
        app.dependency_overrides[current_active_user] = _override_current_user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_admin_can_create_validate_resend_revoke_invitation(api_db: ApiDb) -> None:
    admin = await api_db.seed_user(email="admin@example.com", name="Admin")
    ws = await api_db.seed_workspace(slug="acme", name="Acme")
    await api_db.seed_membership(workspace_id=ws.id, user_id=admin.id, role=Role.ADMIN)

    client = await _client_for(api_db, admin)
    async with client:
        created = await client.post(
            f"/api/v1/workspaces/{ws.id}/invitations",
            json={"email": "qa@example.com", "role": "QA"},
        )
        assert created.status_code == 201
        payload = created.json()
        assert payload["link"].startswith("http://localhost:3000/accept-invite?token=")
        token = payload["link"].split("token=", 1)[1]

        validated = await client.get(f"/api/v1/invitations/validate?token={token}")
        assert validated.status_code == 200
        assert validated.json()["email"] == "qa@example.com"

        resent = await client.post(f"/api/v1/invitations/{payload['id']}/resend")
        assert resent.status_code == 200
        new_token = resent.json()["link"].split("token=", 1)[1]
        assert new_token != token

        revoked = await client.post(f"/api/v1/invitations/{payload['id']}/revoke")
        assert revoked.status_code == 204

        invalid = await client.get(f"/api/v1/invitations/validate?token={new_token}")
        assert invalid.status_code == 404


@pytest.mark.asyncio
async def test_viewer_cannot_create_invitation(api_db: ApiDb) -> None:
    viewer = await api_db.seed_user(email="viewer@example.com", name="Viewer")
    ws = await api_db.member_workspace(viewer, slug="acme", name="Acme")
    client = await _client_for(api_db, viewer)
    async with client:
        response = await client.post(
            f"/api/v1/workspaces/{ws.id}/invitations",
            json={"email": "qa@example.com", "role": "QA"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_accept_invite_creates_user_membership_and_session(api_db: ApiDb) -> None:
    admin = await api_db.seed_user(email="admin@example.com", name="Admin")
    ws = await api_db.seed_workspace(slug="acme", name="Acme")
    await api_db.seed_membership(workspace_id=ws.id, user_id=admin.id, role=Role.ADMIN)
    authed = await _client_for(api_db, admin)
    async with authed:
        created = await authed.post(
            f"/api/v1/workspaces/{ws.id}/invitations",
            json={"email": "qa@example.com", "role": "QA"},
        )
    token = created.json()["link"].split("token=", 1)[1]

    public = await _client_for(api_db, None)
    async with public:
        accepted = await public.post(
            "/api/v1/auth/accept-invite",
            json={"token": token, "name": "QA User", "password": "secret123"},
        )

    assert accepted.status_code == 204
    assert "set-cookie" in accepted.headers
    async with api_db.maker() as session:
        user = await session.scalar(select(User).filter_by(email="qa@example.com"))
        assert user is not None
        assert user.name == "QA User"
        assert PasswordHelper().verify_and_update("secret123", user.hashed_password)[0]
        membership = await session.scalar(
            select(Membership).where(
                Membership.workspace_id == ws.id, Membership.user_id == user.id
            )
        )
        assert membership is not None
        assert membership.role == Role.QA


@pytest.mark.asyncio
async def test_invite_rejects_existing_workspace_member(api_db: ApiDb) -> None:
    admin = await api_db.seed_user(email="admin@example.com", name="Admin")
    existing = await api_db.seed_user(email="qa@example.com", name="QA")
    ws = await api_db.seed_workspace(slug="acme", name="Acme")
    await api_db.seed_membership(workspace_id=ws.id, user_id=admin.id, role=Role.ADMIN)
    await api_db.seed_membership(workspace_id=ws.id, user_id=existing.id, role=Role.QA)

    client = await _client_for(api_db, admin)
    async with client:
        response = await client.post(
            f"/api/v1/workspaces/{ws.id}/invitations",
            json={"email": "qa@example.com", "role": "QA"},
        )

    assert response.status_code == 409
