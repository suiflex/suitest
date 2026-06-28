"""POST /workspaces — first-workspace bootstrap from the UI (dogfood blocker #1).

A freshly-registered or invited user has zero workspaces (``on_after_register``
is a no-op in M0), so the only way to bootstrap from an empty install entirely
through the web UI is a create-workspace endpoint that makes the caller the
OWNER and seeds a ZERO-tier capability row (mirrors
``bootstrap_first_install_superadmin``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from api_harness import ApiDb


@pytest.mark.asyncio
async def test_create_workspace_makes_caller_owner(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="ws-creator@example.com")

    async with api_db.client(user) as c:
        resp = await c.post("/api/v1/workspaces", json={"name": "My First Workspace"})

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "My First Workspace"
    assert body["slug"] == "my-first-workspace"
    ws_id = body["id"]

    # The creator must immediately see the workspace in their own list...
    async with api_db.client(user) as c:
        listed = await c.get("/api/v1/workspaces")
    assert ws_id in {w["id"] for w in listed.json()}

    # ...as an OWNER membership.
    async with api_db.client(user) as c:
        me = await c.get("/api/v1/auth/me")
    membership = next(m for m in me.json()["memberships"] if m["workspace_id"] == ws_id)
    assert membership["role"] == "OWNER"


@pytest.mark.asyncio
async def test_create_workspace_derives_slug_when_omitted(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="ws-slug@example.com")

    async with api_db.client(user) as c:
        resp = await c.post("/api/v1/workspaces", json={"name": "Acme QA Team!"})

    assert resp.status_code == 201, resp.text
    assert resp.json()["slug"] == "acme-qa-team"


@pytest.mark.asyncio
async def test_create_workspace_duplicate_slug_returns_409(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="ws-dupe@example.com")
    await api_db.seed_workspace(slug="taken-slug", name="Taken")

    async with api_db.client(user) as c:
        resp = await c.post("/api/v1/workspaces", json={"name": "Mine", "slug": "taken-slug"})

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["error"]["code"] == "DUPLICATE_WORKSPACE_SLUG"


@pytest.mark.asyncio
async def test_create_workspace_requires_auth(api_db: ApiDb) -> None:
    async with api_db.client(None) as c:  # no current-user override → real 401 path
        resp = await c.post("/api/v1/workspaces", json={"name": "Nope"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_workspace_seeds_zero_tier_capability(api_db: ApiDb) -> None:
    """The new workspace resolves to ZERO tier so capabilities load post-bootstrap."""
    user = await api_db.seed_user(email="ws-cap@example.com")

    async with api_db.client(user) as c:
        resp = await c.post("/api/v1/workspaces", json={"name": "Cap WS"})
        ws_id = resp.json()["id"]
        caps = await c.get("/capabilities", headers={"X-Workspace-Id": ws_id})

    assert caps.status_code == 200, caps.text
    assert caps.json()["tier"] == "ZERO"
