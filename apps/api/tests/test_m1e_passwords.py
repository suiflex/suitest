"""M1e password change and super-admin reset tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from api_harness import ApiDb
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport, AsyncClient
from suitest_api.auth.db import get_async_session
from suitest_api.auth.manager import current_active_user
from suitest_api.main import create_app
from suitest_db.models.user import User


async def _client_for(api_db: ApiDb, user: User) -> AsyncClient:
    app = create_app()

    async def _override_session() -> AsyncIterator[object]:
        async with api_db.maker() as session:
            yield session

    async def _override_current_user() -> User:
        async with api_db.maker() as session:
            db_user = await session.get(User, user.id)
            assert db_user is not None
            return db_user

    app.dependency_overrides[get_async_session] = _override_session
    app.dependency_overrides[current_active_user] = _override_current_user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_change_own_password_requires_current_password(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="maya@example.com", name="Maya")
    async with api_db.maker() as session:
        db_user = await session.get(User, user.id)
        assert db_user is not None
        db_user.hashed_password = PasswordHelper().hash("old-password")
        await session.commit()

    client = await _client_for(api_db, user)
    async with client:
        bad = await client.patch(
            "/api/v1/users/me/password",
            json={"current_password": "wrong", "new_password": "new-password"},
        )
        assert bad.status_code == 400

        good = await client.patch(
            "/api/v1/users/me/password",
            json={"current_password": "old-password", "new_password": "new-password"},
        )
        assert good.status_code == 204

    async with api_db.maker() as session:
        changed = await session.get(User, user.id)
        assert changed is not None
        assert PasswordHelper().verify_and_update("new-password", changed.hashed_password)[0]
        assert changed.must_change_password is False


@pytest.mark.asyncio
async def test_superadmin_can_reset_user_password_once(api_db: ApiDb) -> None:
    admin = await api_db.seed_user(email="root@example.com", name="Root")
    target = await api_db.seed_user(email="qa@example.com", name="QA")
    async with api_db.maker() as session:
        db_admin = await session.get(User, admin.id)
        assert db_admin is not None
        db_admin.is_superuser = True
        await session.commit()

    client = await _client_for(api_db, admin)
    async with client:
        response = await client.post(f"/api/v1/admin/users/{target.id}/reset-password")

    assert response.status_code == 200
    payload = response.json()
    assert payload["temporaryPassword"]
    async with api_db.maker() as session:
        changed = await session.get(User, target.id)
        assert changed is not None
        assert PasswordHelper().verify_and_update(
            payload["temporaryPassword"], changed.hashed_password
        )[0]
        assert changed.must_change_password is True


@pytest.mark.asyncio
async def test_non_superadmin_cannot_reset_user_password(api_db: ApiDb) -> None:
    actor = await api_db.seed_user(email="admin@example.com", name="Admin")
    target = await api_db.seed_user(email="qa@example.com", name="QA")

    client = await _client_for(api_db, actor)
    async with client:
        response = await client.post(f"/api/v1/admin/users/{target.id}/reset-password")

    assert response.status_code == 403
