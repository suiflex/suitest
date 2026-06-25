"""Integration tests for /api/v1/agent-plugins CRUD endpoints (M8).

Covers:
  * GET /agent-plugins lists workspace defs + system plugins
  * POST /agent-plugins creates a definition (201, ADMIN/OWNER only)
  * GET /agent-plugins/{name} returns one definition
  * PATCH /agent-plugins/{name} updates the spec
  * DELETE /agent-plugins/{name} soft-deactivates (204)
  * VIEWER → 403 on write endpoints
  * Duplicate name → 409
  * Invalid YAML → 400
  * Cross-workspace isolation — definition not visible in another workspace
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from suitest_db.models.user import User
from suitest_db.models.workspace import Workspace
from suitest_shared.domain.enums import Role

if TYPE_CHECKING:
    from api_harness import ApiDb

# ---------------------------------------------------------------------------
# Shared YAML fixtures
# ---------------------------------------------------------------------------

_SPEC_V1 = yaml.safe_dump(
    {
        "name": "test-agent",
        "version": "1.0.0",
        "display_name": "Test Agent",
        "description": "An agent for testing.",
        "system_prompt": "You are a test agent.",
        "tool_whitelist": ["playwright_mcp.navigate"],
        "requires_tier": "ZERO",
    }
)

_SPEC_V2 = yaml.safe_dump(
    {
        "name": "test-agent",
        "version": "2.0.0",
        "display_name": "Test Agent v2",
        "description": "Updated.",
        "system_prompt": "You are an updated test agent.",
        "tool_whitelist": ["playwright_mcp.navigate", "playwright_mcp.screenshot"],
        "requires_tier": "ZERO",
    }
)

_SPEC_OTHER = yaml.safe_dump(
    {
        "name": "other-agent",
        "version": "1.0.0",
        "display_name": "Other Agent",
        "description": "Another agent.",
        "system_prompt": "You are another agent.",
        "requires_tier": "ZERO",
    }
)

_INVALID_YAML = "this: is: not: valid: yaml: {"

_INVALID_SPEC = yaml.safe_dump(
    {
        "name": "Bad Name With Spaces",  # invalid slug
        "version": "1.0.0",
        "display_name": "Bad",
        "description": "Bad.",
        "system_prompt": "Bad.",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _admin_ws(api_db: ApiDb, slug: str, email: str) -> tuple[User, Workspace]:
    user = await api_db.seed_user(email=email)
    ws = await api_db.seed_workspace(slug=slug, name=slug)
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.ADMIN)
    return user, ws


async def _viewer_in_ws(api_db: ApiDb, ws_id: str, email: str) -> User:
    user = await api_db.seed_user(email=email)
    await api_db.seed_membership(workspace_id=ws_id, user_id=user.id, role=Role.VIEWER)
    return user


# ---------------------------------------------------------------------------
# GET /agent-plugins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_agent_plugins_empty(api_db: ApiDb) -> None:
    """Empty workspace returns empty workspace_definitions list."""
    user, ws = await _admin_ws(api_db, "ap-list-empty", "ap-list-empty@example.com")
    async with api_db.client(user) as c:
        resp = await c.get(
            "/api/v1/agent-plugins",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["workspace_definitions"] == []
    assert isinstance(body["system_plugins"], list)


@pytest.mark.asyncio
async def test_list_agent_plugins_shows_registered(api_db: ApiDb) -> None:
    """POST then GET list returns the definition."""
    user, ws = await _admin_ws(api_db, "ap-list-reg", "ap-list-reg@example.com")
    async with api_db.client(user) as c:
        await c.post(
            "/api/v1/agent-plugins",
            json={"spec_yaml": _SPEC_V1},
            headers={"X-Workspace-Id": ws.id},
        )
        resp = await c.get(
            "/api/v1/agent-plugins",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    defs = resp.json()["workspace_definitions"]
    assert len(defs) == 1
    assert defs[0]["name"] == "test-agent"
    assert defs[0]["spec_version"] == "1.0.0"


# ---------------------------------------------------------------------------
# POST /agent-plugins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_agent_plugin_creates_201(api_db: ApiDb) -> None:
    """Admin can create a definition; response is 201 with correct fields."""
    user, ws = await _admin_ws(api_db, "ap-post-ok", "ap-post-ok@example.com")
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/agent-plugins",
            json={"spec_yaml": _SPEC_V1},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "test-agent"
    assert body["spec_version"] == "1.0.0"
    assert body["is_active"] is True
    assert body["workspace_id"] == ws.id
    assert body["spec"]["name"] == "test-agent"


@pytest.mark.asyncio
async def test_post_agent_plugin_viewer_returns_403(api_db: ApiDb) -> None:
    """VIEWER cannot register definitions."""
    _user, ws = await _admin_ws(api_db, "ap-post-viewer", "ap-post-viewer-admin@example.com")
    viewer = await _viewer_in_ws(api_db, ws.id, "ap-post-viewer@example.com")
    async with api_db.client(viewer) as c:
        resp = await c.post(
            "/api/v1/agent-plugins",
            json={"spec_yaml": _SPEC_V1},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_agent_plugin_duplicate_returns_409(api_db: ApiDb) -> None:
    """Registering the same name twice → 409."""
    user, ws = await _admin_ws(api_db, "ap-post-dup", "ap-post-dup@example.com")
    async with api_db.client(user) as c:
        await c.post(
            "/api/v1/agent-plugins",
            json={"spec_yaml": _SPEC_V1},
            headers={"X-Workspace-Id": ws.id},
        )
        resp = await c.post(
            "/api/v1/agent-plugins",
            json={"spec_yaml": _SPEC_V1},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"]["code"] == "AGENT_DEFINITION_DUPLICATE"


@pytest.mark.asyncio
async def test_post_agent_plugin_invalid_yaml_returns_400(api_db: ApiDb) -> None:
    """Malformed YAML → 400."""
    user, ws = await _admin_ws(api_db, "ap-post-badyaml", "ap-post-badyaml@example.com")
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/agent-plugins",
            json={"spec_yaml": _INVALID_YAML},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "AGENT_SPEC_INVALID"


@pytest.mark.asyncio
async def test_post_agent_plugin_invalid_spec_returns_400(api_db: ApiDb) -> None:
    """Valid YAML but invalid spec (bad name slug) → 400."""
    user, ws = await _admin_ws(api_db, "ap-post-badspec", "ap-post-badspec@example.com")
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/agent-plugins",
            json={"spec_yaml": _INVALID_SPEC},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "AGENT_SPEC_INVALID"


# ---------------------------------------------------------------------------
# GET /agent-plugins/{name}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_agent_plugin_by_name(api_db: ApiDb) -> None:
    """GET /{name} returns the correct definition."""
    user, ws = await _admin_ws(api_db, "ap-get-one", "ap-get-one@example.com")
    async with api_db.client(user) as c:
        await c.post(
            "/api/v1/agent-plugins",
            json={"spec_yaml": _SPEC_V1},
            headers={"X-Workspace-Id": ws.id},
        )
        resp = await c.get(
            "/api/v1/agent-plugins/test-agent",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    assert resp.json()["name"] == "test-agent"


@pytest.mark.asyncio
async def test_get_agent_plugin_not_found_returns_404(api_db: ApiDb) -> None:
    user, ws = await _admin_ws(api_db, "ap-get-404", "ap-get-404@example.com")
    async with api_db.client(user) as c:
        resp = await c.get(
            "/api/v1/agent-plugins/nonexistent-agent",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /agent-plugins/{name}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_agent_plugin_updates_spec(api_db: ApiDb) -> None:
    """PATCH updates version and YAML."""
    user, ws = await _admin_ws(api_db, "ap-patch-ok", "ap-patch-ok@example.com")
    async with api_db.client(user) as c:
        await c.post(
            "/api/v1/agent-plugins",
            json={"spec_yaml": _SPEC_V1},
            headers={"X-Workspace-Id": ws.id},
        )
        resp = await c.patch(
            "/api/v1/agent-plugins/test-agent",
            json={"spec_yaml": _SPEC_V2},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["spec_version"] == "2.0.0"
    assert body["spec"]["version"] == "2.0.0"


@pytest.mark.asyncio
async def test_patch_agent_plugin_not_found_returns_404(api_db: ApiDb) -> None:
    user, ws = await _admin_ws(api_db, "ap-patch-404", "ap-patch-404@example.com")
    async with api_db.client(user) as c:
        resp = await c.patch(
            "/api/v1/agent-plugins/ghost-agent",
            json={"spec_yaml": _SPEC_V1},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_agent_plugin_viewer_returns_403(api_db: ApiDb) -> None:
    _user, ws = await _admin_ws(api_db, "ap-patch-viewer", "ap-patch-viewer-admin@example.com")
    viewer = await _viewer_in_ws(api_db, ws.id, "ap-patch-viewer@example.com")
    async with api_db.client(viewer) as c:
        resp = await c.patch(
            "/api/v1/agent-plugins/test-agent",
            json={"spec_yaml": _SPEC_V2},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /agent-plugins/{name}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_agent_plugin_deactivates(api_db: ApiDb) -> None:
    """DELETE soft-deactivates; subsequent GET returns 404."""
    user, ws = await _admin_ws(api_db, "ap-del-ok", "ap-del-ok@example.com")
    async with api_db.client(user) as c:
        await c.post(
            "/api/v1/agent-plugins",
            json={"spec_yaml": _SPEC_V1},
            headers={"X-Workspace-Id": ws.id},
        )
        del_resp = await c.delete(
            "/api/v1/agent-plugins/test-agent",
            headers={"X-Workspace-Id": ws.id},
        )
        get_resp = await c.get(
            "/api/v1/agent-plugins/test-agent",
            headers={"X-Workspace-Id": ws.id},
        )
    assert del_resp.status_code == 204
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_agent_plugin_not_found_returns_404(api_db: ApiDb) -> None:
    user, ws = await _admin_ws(api_db, "ap-del-404", "ap-del-404@example.com")
    async with api_db.client(user) as c:
        resp = await c.delete(
            "/api/v1/agent-plugins/ghost",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_agent_plugin_viewer_returns_403(api_db: ApiDb) -> None:
    _user, ws = await _admin_ws(api_db, "ap-del-viewer", "ap-del-viewer-admin@example.com")
    viewer = await _viewer_in_ws(api_db, ws.id, "ap-del-viewer@example.com")
    async with api_db.client(viewer) as c:
        resp = await c.delete(
            "/api/v1/agent-plugins/test-agent",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Cross-workspace isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_plugin_cross_workspace_isolation(api_db: ApiDb) -> None:
    """Definition registered in ws-A is not visible from ws-B."""
    user_a, ws_a = await _admin_ws(api_db, "ap-iso-a", "ap-iso-a@example.com")
    user_b, ws_b = await _admin_ws(api_db, "ap-iso-b", "ap-iso-b@example.com")

    async with api_db.client(user_a) as c:
        await c.post(
            "/api/v1/agent-plugins",
            json={"spec_yaml": _SPEC_V1},
            headers={"X-Workspace-Id": ws_a.id},
        )

    async with api_db.client(user_b) as c:
        resp = await c.get(
            "/api/v1/agent-plugins/test-agent",
            headers={"X-Workspace-Id": ws_b.id},
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Re-register after deactivation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reregister_after_delete_succeeds(api_db: ApiDb) -> None:
    """After DELETE, the same name can be registered again (201)."""
    user, ws = await _admin_ws(api_db, "ap-rereg", "ap-rereg@example.com")
    async with api_db.client(user) as c:
        await c.post(
            "/api/v1/agent-plugins",
            json={"spec_yaml": _SPEC_V1},
            headers={"X-Workspace-Id": ws.id},
        )
        await c.delete(
            "/api/v1/agent-plugins/test-agent",
            headers={"X-Workspace-Id": ws.id},
        )
        resp = await c.post(
            "/api/v1/agent-plugins",
            json={"spec_yaml": _SPEC_V1},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 201
    assert resp.json()["spec_version"] == "1.0.0"
