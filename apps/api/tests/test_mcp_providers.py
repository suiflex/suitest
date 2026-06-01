"""Tests for the MCP provider registry CRUD (M2-6) — ``/api/v1/mcp/providers``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.mcp_provider import McpProvider
from suitest_mcp.providers.builtin_specs import BUILTIN_SPECS
from suitest_shared.domain.enums import McpTransport, Role

if TYPE_CHECKING:
    from api_harness import ApiDb

_BUILTIN_NAMES = {spec.name for spec in BUILTIN_SPECS}


def _h(ws_id: str) -> dict[str, str]:
    return {"X-Workspace-Id": ws_id}


# --------------------------------------------------------------------------- list


@pytest.mark.asyncio
async def test_list_returns_bundled_builtins_on_empty_workspace(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="mcp-empty@example.com")
    ws = await api_db.member_workspace(user, slug="mcp-empty-ws")
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/mcp/providers", headers=_h(ws.id))
    assert resp.status_code == 200
    items = resp.json()["items"]
    names = {row["name"] for row in items}
    assert names >= _BUILTIN_NAMES
    assert all(row["isBundled"] for row in items if row["name"] in _BUILTIN_NAMES)


@pytest.mark.asyncio
async def test_list_merges_builtins_and_custom_rows(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="mcp-list@example.com")
    ws = await api_db.member_workspace(user, slug="mcp-list-ws")
    await api_db.add_all(
        [
            McpProvider(
                workspace_id=ws.id,
                name="vendor-x-http",
                kind="http",
                endpoint="https://mcp.vendor.example/sse",
                transport=McpTransport.SSE,
            ),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/mcp/providers", headers=_h(ws.id))
    assert resp.status_code == 200
    items = resp.json()["items"]
    names = {row["name"] for row in items}
    assert "vendor-x-http" in names
    assert names >= _BUILTIN_NAMES
    custom = next(r for r in items if r["name"] == "vendor-x-http")
    assert custom["isBundled"] is False
    for row in items:
        assert "secrets_json_encrypted" not in row
        assert "secretsJsonEncrypted" not in row


@pytest.mark.asyncio
async def test_list_workspace_isolated(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="mcp-iso@example.com")
    ws = await api_db.member_workspace(user, slug="mcp-iso-ws")
    other = await api_db.seed_workspace(slug="mcp-iso-other", name="Other")
    await api_db.add_all(
        [
            McpProvider(
                workspace_id=other.id,
                name="cross-ws",
                kind="http",
                endpoint="stdio://x",
                transport=McpTransport.STDIO,
            ),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/mcp/providers", headers=_h(ws.id))
    items = resp.json()["items"]
    assert "cross-ws" not in {row["name"] for row in items}


# --------------------------------------------------------------------------- create


@pytest.mark.asyncio
async def test_create_custom_provider(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="mcp-create@example.com")
    ws = await api_db.member_workspace(user, slug="mcp-create-ws")
    body = {
        "name": "payments-mcp",
        "kind": "payments",
        "endpoint": "node ./mcp/payments/index.js",
        "transport": "stdio",
        "secretsJson": {"stripe_key": "sk_test_xxx"},
        "isDefaultForTarget": {"BE_REST": True},
    }
    async with api_db.client(user) as c:
        resp = await c.post("/api/v1/mcp/providers", json=body, headers=_h(ws.id))
    assert resp.status_code == 201, resp.text
    detail = resp.json()
    assert detail["name"] == "payments-mcp"
    assert detail["isBundled"] is False
    assert detail["hasSecrets"] is True
    assert detail["configJson"]["command"] == ["node", "./mcp/payments/index.js"]
    assert "stripe_key" not in resp.text
    assert detail["isDefaultForTarget"] == {"BE_REST": True}


@pytest.mark.asyncio
async def test_create_duplicate_name_conflicts(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="mcp-dup@example.com")
    ws = await api_db.member_workspace(user, slug="mcp-dup-ws")
    body = {"name": "dup-mcp", "kind": "x", "endpoint": "cmd", "transport": "stdio"}
    async with api_db.client(user) as c:
        first = await c.post("/api/v1/mcp/providers", json=body, headers=_h(ws.id))
        second = await c.post("/api/v1/mcp/providers", json=body, headers=_h(ws.id))
    assert first.status_code == 201
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_create_requires_write_role(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="mcp-viewer@example.com")
    ws = await api_db.seed_workspace(slug="mcp-viewer-ws", name="Viewer WS")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    body = {"name": "blocked-mcp", "kind": "x", "endpoint": "cmd", "transport": "stdio"}
    async with api_db.client(user) as c:
        resp = await c.post("/api/v1/mcp/providers", json=body, headers=_h(ws.id))
    assert resp.status_code == 403


# --------------------------------------------------------- get / patch / delete


@pytest.mark.asyncio
async def test_get_create_patch_delete_roundtrip(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="mcp-rt@example.com")
    ws = await api_db.member_workspace(user, slug="mcp-rt-ws")
    async with api_db.client(user) as c:
        created = await c.post(
            "/api/v1/mcp/providers",
            json={"name": "rt-mcp", "kind": "x", "endpoint": "https://h/sse", "transport": "sse"},
            headers=_h(ws.id),
        )
        pid = created.json()["id"]

        got = await c.get(f"/api/v1/mcp/providers/{pid}", headers=_h(ws.id))
        assert got.status_code == 200
        assert got.json()["name"] == "rt-mcp"

        patched = await c.patch(
            f"/api/v1/mcp/providers/{pid}",
            json={"kind": "graphql", "enabled": False},
            headers=_h(ws.id),
        )
        assert patched.status_code == 200
        assert patched.json()["kind"] == "graphql"
        assert patched.json()["enabled"] is False

        deleted = await c.delete(f"/api/v1/mcp/providers/{pid}", headers=_h(ws.id))
        assert deleted.status_code == 204

        gone = await c.get(f"/api/v1/mcp/providers/{pid}", headers=_h(ws.id))
        assert gone.status_code == 404


@pytest.mark.asyncio
async def test_builtin_detail_readonly(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="mcp-builtin@example.com")
    ws = await api_db.member_workspace(user, slug="mcp-builtin-ws")
    spec = BUILTIN_SPECS[0]
    async with api_db.client(user) as c:
        got = await c.get(f"/api/v1/mcp/providers/{spec.id}", headers=_h(ws.id))
        assert got.status_code == 200
        assert got.json()["isBundled"] is True

        patched = await c.patch(
            f"/api/v1/mcp/providers/{spec.id}", json={"kind": "x"}, headers=_h(ws.id)
        )
        assert patched.status_code == 409

        deleted = await c.delete(f"/api/v1/mcp/providers/{spec.id}", headers=_h(ws.id))
        assert deleted.status_code == 409


@pytest.mark.asyncio
async def test_get_other_workspace_provider_404(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="mcp-x@example.com")
    ws = await api_db.member_workspace(user, slug="mcp-x-ws")
    other = await api_db.seed_workspace(slug="mcp-x-other", name="Other")
    await api_db.add_all(
        [
            McpProvider(
                id="mcpxotherrow0000000000000000",
                workspace_id=other.id,
                name="other-mcp",
                kind="x",
                endpoint="cmd",
                transport=McpTransport.STDIO,
            ),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/mcp/providers/mcpxotherrow0000000000000000", headers=_h(ws.id))
    assert resp.status_code == 404
