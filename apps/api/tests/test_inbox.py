"""Tests for ``GET /api/v1/inbox`` (CRITICAL C4 stub)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from api_harness import ApiDb


@pytest.mark.asyncio
async def test_inbox_returns_empty_envelope(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="inbox@example.com")
    ws = await api_db.member_workspace(user, slug="inbox-ws")
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/inbox", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["unreadCount"] == 0


@pytest.mark.asyncio
async def test_inbox_requires_workspace_membership(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="inbox-403@example.com")
    other = await api_db.seed_workspace(slug="inbox-403-other", name="Other")
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/inbox", headers={"X-Workspace-Id": other.id})
    assert resp.status_code == 403
