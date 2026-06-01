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
        "validate": False,
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
    body = {
        "name": "dup-mcp",
        "kind": "x",
        "endpoint": "cmd",
        "transport": "stdio",
        "validate": False,
    }
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
            json={
                "name": "rt-mcp",
                "kind": "x",
                "endpoint": "https://h/sse",
                "transport": "sse",
                "validate": False,
            },
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


# --------------------------------------------- M2-7: register-time validation

_MOCK_MCP_SCRIPT = """
import asyncio, json
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

app = Server("probe-mock")

@app.list_tools()
async def list_tools():
    return [Tool(name="echo", description="echo back", inputSchema={"type": "object"})]

@app.call_tool()
async def call_tool(name, arguments):
    return [TextContent(type="text", text=json.dumps(arguments))]

async def main():
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
"""


def _mock_command(tmp_path: object) -> str:
    import sys
    from pathlib import Path

    script = Path(str(tmp_path)) / "probe_mcp_server.py"
    script.write_text(_MOCK_MCP_SCRIPT)
    return f"{sys.executable} {script}"


@pytest.mark.asyncio
async def test_register_with_validation_discovers_tools(api_db: ApiDb, tmp_path: object) -> None:
    user = await api_db.seed_user(email="mcp-v7@example.com")
    ws = await api_db.member_workspace(user, slug="mcp-v7-ws")
    body = {
        "name": "probe-mcp",
        "kind": "custom",
        "endpoint": _mock_command(tmp_path),
        "transport": "stdio",
        # validate defaults to True — real connect + tools/list happens here.
    }
    async with api_db.client(user) as c:
        resp = await c.post("/api/v1/mcp/providers", json=body, headers=_h(ws.id))
    assert resp.status_code == 201, resp.text
    detail = resp.json()
    assert detail["healthStatus"] == "ok"
    assert {t["name"] for t in detail["tools"]} == {"echo"}


@pytest.mark.asyncio
async def test_register_validation_failure_rejects(api_db: ApiDb, tmp_path: object) -> None:
    import sys
    from pathlib import Path

    missing = Path(str(tmp_path)) / "nope.py"
    user = await api_db.seed_user(email="mcp-v7fail@example.com")
    ws = await api_db.member_workspace(user, slug="mcp-v7fail-ws")
    body = {
        "name": "broken-mcp",
        "kind": "custom",
        "endpoint": f"{sys.executable} {missing}",
        "transport": "stdio",
    }
    async with api_db.client(user) as c:
        resp = await c.post("/api/v1/mcp/providers", json=body, headers=_h(ws.id))
        listed = await c.get("/api/v1/mcp/providers", headers=_h(ws.id))
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "MCP_REGISTRATION_FAILED"
    assert "broken-mcp" not in {r["name"] for r in listed.json()["items"]}


@pytest.mark.asyncio
async def test_test_connection_endpoint(api_db: ApiDb, tmp_path: object) -> None:
    user = await api_db.seed_user(email="mcp-tc@example.com")
    ws = await api_db.member_workspace(user, slug="mcp-tc-ws")
    body = {
        "name": "probe-mcp",
        "kind": "custom",
        "endpoint": _mock_command(tmp_path),
        "transport": "stdio",
    }
    async with api_db.client(user) as c:
        resp = await c.post("/api/v1/mcp/providers/test-connection", json=body, headers=_h(ws.id))
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["ok"] is True
    assert {t["name"] for t in payload["tools"]} == {"echo"}


# --------------------------------------------- M2-8: tool browser (discover + invoke)


@pytest.mark.asyncio
async def test_discover_refreshes_tool_catalog(api_db: ApiDb, tmp_path: object) -> None:
    user = await api_db.seed_user(email="mcp-disc@example.com")
    ws = await api_db.member_workspace(user, slug="mcp-disc-ws")
    cmd = _mock_command(tmp_path)
    async with api_db.client(user) as c:
        created = await c.post(
            "/api/v1/mcp/providers",
            json={"name": "disc-mcp", "kind": "custom", "endpoint": cmd, "transport": "stdio"},
            headers=_h(ws.id),
        )
        pid = created.json()["id"]
        disc = await c.post(f"/api/v1/mcp/providers/{pid}/discover", headers=_h(ws.id))
    assert disc.status_code == 200, disc.text
    body = disc.json()
    assert body["healthStatus"] == "ok"
    assert {t["name"] for t in body["tools"]} == {"echo"}


@pytest.mark.asyncio
async def test_invoke_requires_admin(api_db: ApiDb, tmp_path: object) -> None:
    user = await api_db.seed_user(email="mcp-inv-qa@example.com")
    ws = await api_db.member_workspace(user, slug="mcp-inv-qa-ws")  # QA role
    cmd = _mock_command(tmp_path)
    async with api_db.client(user) as c:
        created = await c.post(
            "/api/v1/mcp/providers",
            json={"name": "inv-mcp", "kind": "custom", "endpoint": cmd, "transport": "stdio"},
            headers=_h(ws.id),
        )
        pid = created.json()["id"]
        resp = await c.post(
            f"/api/v1/mcp/providers/{pid}/invoke",
            json={"tool": "echo", "arguments": {"x": 1}},
            headers=_h(ws.id),
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_invoke_executes_tool_for_admin(api_db: ApiDb, tmp_path: object) -> None:
    user = await api_db.seed_user(email="mcp-inv-admin@example.com")
    ws = await api_db.seed_workspace(slug="mcp-inv-admin-ws", name="Admin WS")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.OWNER)
    cmd = _mock_command(tmp_path)
    async with api_db.client(user) as c:
        created = await c.post(
            "/api/v1/mcp/providers",
            json={"name": "inv2-mcp", "kind": "custom", "endpoint": cmd, "transport": "stdio"},
            headers=_h(ws.id),
        )
        pid = created.json()["id"]
        resp = await c.post(
            f"/api/v1/mcp/providers/{pid}/invoke",
            json={"tool": "echo", "arguments": {"ping": "pong"}},
            headers=_h(ws.id),
        )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["ok"] is True
    assert "pong" in payload["stdout"]


@pytest.mark.asyncio
async def test_invoke_builtin_rejected(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="mcp-inv-builtin@example.com")
    ws = await api_db.seed_workspace(slug="mcp-inv-builtin-ws", name="Admin WS")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.OWNER)
    spec = BUILTIN_SPECS[0]
    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/mcp/providers/{spec.id}/invoke",
            json={"tool": "http.request", "arguments": {}},
            headers=_h(ws.id),
        )
    assert resp.status_code == 409
