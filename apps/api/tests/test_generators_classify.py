"""Tests for ``POST /api/v1/generators/classify`` (M2 Task 1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.mcp_provider import McpProvider
from suitest_shared.domain.enums import McpTransport, Role

if TYPE_CHECKING:
    from api_harness import ApiDb


@pytest.mark.asyncio
async def test_classify_openapi_url_resolves_registered_provider(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="gen-openapi@example.com")
    ws = await api_db.member_workspace(user, slug="gen-openapi-ws")
    await api_db.add_all(
        [
            McpProvider(
                workspace_id=ws.id,
                name="api-http-mcp",
                kind="api",
                endpoint="stdio://api-http-mcp",
                transport=McpTransport.STDIO,
            ),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/generators/classify",
            headers={"X-Workspace-Id": ws.id},
            json={"kind": "url", "value": "https://api.example.com/openapi.json"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["target_kind"] == "BE_REST"
    assert body["recommended_strategy"] == "openapi-generator"
    assert body["recommended_mcp"]["name"] == "api-http-mcp"
    assert body["recommended_mcp"]["id"] is not None
    assert 0.0 <= body["confidence"] <= 1.0


@pytest.mark.asyncio
async def test_classify_provider_not_registered_id_none(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="gen-noprov@example.com")
    ws = await api_db.member_workspace(user, slug="gen-noprov-ws")
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/generators/classify",
            headers={"X-Workspace-Id": ws.id},
            json={"kind": "url", "value": "https://api.example.com/openapi.json"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["recommended_mcp"]["name"] == "api-http-mcp"
    assert body["recommended_mcp"]["id"] is None


@pytest.mark.asyncio
async def test_classify_unauthenticated(api_db: ApiDb) -> None:
    # No user override → real FastAPI-Users dep runs → 401.
    async with api_db.client(None) as c:
        resp = await c.post(
            "/api/v1/generators/classify",
            headers={"X-Workspace-Id": "00000000-0000-0000-0000-000000000000"},
            json={"kind": "url", "value": "https://api.example.com/openapi.json"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_classify_viewer_role_forbidden(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="gen-viewer@example.com")
    ws = await api_db.seed_workspace(slug="gen-viewer-ws", name="Viewer WS")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/generators/classify",
            headers={"X-Workspace-Id": ws.id},
            json={"kind": "url", "value": "https://api.example.com/openapi.json"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_classify_cross_workspace_provider_resolution(api_db: ApiDb) -> None:
    # Register api-http-mcp in workspace A only; classify as a user in workspace B.
    user = await api_db.seed_user(email="gen-xws@example.com")
    ws_b = await api_db.member_workspace(user, slug="gen-xws-b")
    ws_a = await api_db.seed_workspace(slug="gen-xws-a", name="WS A")
    await api_db.add_all(
        [
            McpProvider(
                workspace_id=ws_a.id,
                name="api-http-mcp",
                kind="api",
                endpoint="stdio://api-http-mcp",
                transport=McpTransport.STDIO,
            ),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/generators/classify",
            headers={"X-Workspace-Id": ws_b.id},
            json={"kind": "url", "value": "https://api.example.com/openapi.json"},
        )
    assert resp.status_code == 200
    body = resp.json()
    # No cross-tenant leak: provider belongs to ws A, caller is in ws B.
    assert body["recommended_mcp"]["id"] is None


@pytest.mark.asyncio
async def test_classify_validation_error(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="gen-422@example.com")
    ws = await api_db.member_workspace(user, slug="gen-422-ws")
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/generators/classify",
            headers={"X-Workspace-Id": ws.id},
            json={"kind": "url", "value": ""},
        )
    assert resp.status_code == 422
