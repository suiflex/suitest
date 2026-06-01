"""M1e first-install super-admin bootstrap tests."""

from __future__ import annotations

import uuid

import pytest
from api_harness import ApiDb
from fastapi_users.password import PasswordHelper
from sqlalchemy import func, select
from suitest_api.services.bootstrap import bootstrap_first_install_superadmin
from suitest_api.settings import Settings
from suitest_db.models.tenancy import Membership
from suitest_db.models.user import User
from suitest_db.models.workspace import Workspace
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_shared.domain.enums import Role, Tier


def _settings(email: str = "root@example.com", password: str = "secret123") -> Settings:
    return Settings(
        superadmin_email=email,
        superadmin_password=password,
        superadmin_workspace_name="Acme QA",
    )


@pytest.mark.asyncio
async def test_bootstrap_creates_superadmin_workspace_membership_and_capability(
    api_db: ApiDb,
) -> None:
    async with api_db.maker() as session:
        created = await bootstrap_first_install_superadmin(session, _settings())
        await session.commit()

    assert created is True
    async with api_db.maker() as session:
        user = await session.scalar(select(User).filter_by(email="root@example.com"))
        assert user is not None
        assert user.is_superuser is True
        assert user.is_verified is True
        assert user.name == "root"
        assert PasswordHelper().verify_and_update("secret123", user.hashed_password)[0] is True

        workspace = await session.scalar(select(Workspace).filter_by(name="Acme QA"))
        assert workspace is not None

        membership = await session.scalar(
            select(Membership).where(
                Membership.workspace_id == workspace.id,
                Membership.user_id == user.id,
            )
        )
        assert membership is not None
        assert membership.role == Role.OWNER

        capability = await session.scalar(
            select(WorkspaceCapability).where(WorkspaceCapability.workspace_id == workspace.id)
        )
        assert capability is not None
        assert capability.tier == Tier.ZERO


@pytest.mark.asyncio
async def test_bootstrap_skips_when_any_user_exists(api_db: ApiDb) -> None:
    await api_db.seed_user(email="existing@example.com")

    async with api_db.maker() as session:
        created = await bootstrap_first_install_superadmin(session, _settings())
        await session.commit()

    assert created is False
    async with api_db.maker() as session:
        user_count = await session.scalar(select(func.count()).select_from(User))
        workspace_count = await session.scalar(select(func.count()).select_from(Workspace))
    assert user_count == 1
    assert workspace_count == 0


@pytest.mark.asyncio
async def test_bootstrap_skips_when_env_is_incomplete(api_db: ApiDb) -> None:
    async with api_db.maker() as session:
        created = await bootstrap_first_install_superadmin(
            session,
            Settings(superadmin_email="", superadmin_password=""),
        )
        await session.commit()

    assert created is False
    async with api_db.maker() as session:
        user_count = await session.scalar(select(func.count()).select_from(User))
    assert user_count == 0


@pytest.mark.asyncio
async def test_bootstrap_ignores_invalid_existing_ids(api_db: ApiDb) -> None:
    """Existing users can have arbitrary UUIDs; count-based guard still skips."""
    async with api_db.maker() as session:
        session.add(
            User(
                id=uuid.uuid4(),
                email="someone@example.com",
                hashed_password="x",
                is_active=True,
                is_superuser=False,
                is_verified=True,
                name="Someone",
            )
        )
        await session.commit()

        created = await bootstrap_first_install_superadmin(session, _settings())
        await session.commit()

    assert created is False
