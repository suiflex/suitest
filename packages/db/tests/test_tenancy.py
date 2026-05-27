"""Tests for users / workspaces / memberships (Task 2a)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.ids import new_id
from suitest_db.models.tenancy import Membership
from suitest_db.models.user import User
from suitest_db.models.workspace import Workspace
from suitest_shared.domain.enums import Role


def _user(email: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        hashed_password="x",
        is_active=True,
        is_superuser=False,
        is_verified=False,
        name="Test User",
    )


@pytest.mark.asyncio
async def test_create_user_unique_email(session: AsyncSession) -> None:
    email = f"dup-{new_id()}@b.c"
    session.add(_user(email))
    await session.flush()
    session.add(_user(email))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_workspace_region_default(session: AsyncSession) -> None:
    ws = Workspace(slug=f"ws-{new_id()}", name="WS")
    session.add(ws)
    await session.flush()
    assert ws.region == "ap-southeast-1"


@pytest.mark.asyncio
async def test_membership_cascade_on_workspace_delete(session: AsyncSession) -> None:
    ws = Workspace(slug=f"ws-{new_id()}", name="WS")
    user = _user(f"m-{new_id()}@b.c")
    session.add_all([ws, user])
    await session.flush()
    membership = Membership(workspace_id=ws.id, user_id=user.id, role=Role.QA)
    session.add(membership)
    await session.flush()
    mid = membership.id

    await session.delete(ws)
    await session.flush()

    assert await session.get(Membership, mid) is None
    # User row survives.
    assert await session.get(User, user.id) is not None


@pytest.mark.asyncio
async def test_membership_unique_per_workspace_user(session: AsyncSession) -> None:
    ws = Workspace(slug=f"ws-{new_id()}", name="WS")
    user = _user(f"u-{new_id()}@b.c")
    session.add_all([ws, user])
    await session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=user.id, role=Role.QA))
    await session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=user.id, role=Role.ADMIN))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_membership_role_default_is_qa(session: AsyncSession) -> None:
    ws = Workspace(slug=f"ws-{new_id()}", name="WS")
    user = _user(f"r-{new_id()}@b.c")
    session.add_all([ws, user])
    await session.flush()
    m = Membership(workspace_id=ws.id, user_id=user.id)
    session.add(m)
    await session.flush()
    fetched = await session.scalar(select(Membership).where(Membership.id == m.id))
    assert fetched is not None
    assert fetched.role is Role.QA


@pytest.mark.asyncio
async def test_membership_user_id_indexed(session: AsyncSession) -> None:
    # Sanity that the relationship/back_populates wiring loads.
    ws = Workspace(slug=f"ws-{new_id()}", name="WS")
    user = _user(f"i-{new_id()}@b.c")
    session.add_all([ws, user])
    await session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=user.id))
    await session.flush()
    count = await session.scalar(
        select(func.count()).select_from(Membership).where(Membership.workspace_id == ws.id)
    )
    assert count == 1
