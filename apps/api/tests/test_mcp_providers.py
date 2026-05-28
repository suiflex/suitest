"""Tests for ``GET /api/v1/mcp/providers`` (CRITICAL C4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.mcp_provider import McpProvider
from suitest_shared.domain.enums import McpTransport

if TYPE_CHECKING:
    from api_harness import ApiDb


@pytest.mark.asyncio
async def test_mcp_providers_empty_workspace(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="mcp-empty@example.com")
    ws = await api_db.member_workspace(user, slug="mcp-empty-ws")
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/mcp/providers", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


@pytest.mark.asyncio
async def test_mcp_providers_lists_workspace_rows(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="mcp-list@example.com")
    ws = await api_db.member_workspace(user, slug="mcp-list-ws")
    await api_db.add_all(
        [
            McpProvider(
                workspace_id=ws.id,
                name="Playwright MCP",
                kind="playwright",
                endpoint="stdio://playwright-mcp",
                transport=McpTransport.STDIO,
            ),
            McpProvider(
                workspace_id=ws.id,
                name="HTTP API MCP",
                kind="api",
                endpoint="stdio://api-http-mcp",
                transport=McpTransport.STDIO,
            ),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/mcp/providers", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    body = resp.json()
    names = {row["name"] for row in body["items"]}
    assert names == {"Playwright MCP", "HTTP API MCP"}
    # Secrets must never reach the response.
    for row in body["items"]:
        assert "secrets_json_encrypted" not in row
        assert "secretsJsonEncrypted" not in row


@pytest.mark.asyncio
async def test_mcp_providers_workspace_isolated(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="mcp-iso@example.com")
    ws = await api_db.member_workspace(user, slug="mcp-iso-ws")
    other = await api_db.seed_workspace(slug="mcp-iso-other", name="Other")
    await api_db.add_all(
        [
            McpProvider(
                workspace_id=other.id,
                name="Cross WS",
                kind="playwright",
                endpoint="stdio://x",
                transport=McpTransport.STDIO,
            ),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/mcp/providers", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    assert resp.json() == {"items": []}
