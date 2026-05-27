"""Task 7a — auth/me + workspace read endpoint tests (docs/API.md §3.1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from conftest import ApiDb


@pytest.mark.asyncio
async def test_me_returns_user_and_memberships(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="me-a@example.com")
    ws = await api_db.seed_workspace(slug="me-ws-a", name="Me WS A")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id)

    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "me-a@example.com"
    assert len(data["memberships"]) == 1
    assert data["memberships"][0]["workspace_id"] == ws.id
    assert data["memberships"][0]["workspace"]["slug"] == "me-ws-a"


@pytest.mark.asyncio
async def test_me_requires_auth(api_db: ApiDb) -> None:
    async with api_db.client(None) as c:  # no current-user override → real 401 path
        resp = await c.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_workspaces_lists_only_members(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="member-a@example.com")
    ws1 = await api_db.seed_workspace(slug="list-ws1", name="List WS1")
    ws2 = await api_db.seed_workspace(slug="list-ws2", name="List WS2")
    await api_db.seed_membership(workspace_id=ws1.id, user_id=user.id)

    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/workspaces")
    assert resp.status_code == 200
    ids = {w["id"] for w in resp.json()}
    assert ids == {ws1.id}
    assert ws2.id not in ids


@pytest.mark.asyncio
async def test_workspace_detail_403_when_non_member(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="nonmember@example.com")
    other = await api_db.seed_workspace(slug="detail-other", name="Other")
    # user has NO membership in `other`.

    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/workspaces/{other.id}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_workspace_members_lists_all(api_db: ApiDb) -> None:
    owner = await api_db.seed_user(email="owner@example.com", name="Owner")
    member = await api_db.seed_user(email="member2@example.com", name="Member Two")
    ws = await api_db.seed_workspace(slug="members-ws", name="Members WS")
    await api_db.seed_membership(workspace_id=ws.id, user_id=owner.id)
    await api_db.seed_membership(workspace_id=ws.id, user_id=member.id)

    async with api_db.client(owner) as c:
        resp = await c.get(f"/api/v1/workspaces/{ws.id}/members")
    assert resp.status_code == 200
    emails = {row["email"] for row in resp.json()}
    assert emails == {"owner@example.com", "member2@example.com"}
