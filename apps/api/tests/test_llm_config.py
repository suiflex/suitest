"""M3-2 + M3-3 tests — ``/api/v1/workspaces/:id/llm-config`` + tier refresh.

Uses the ``mock`` provider (a CLOUD-tier sentinel) so connection tests round-trip
the deterministic MockProvider with no network. Requires Postgres (api_db).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_shared.domain.enums import Role

if TYPE_CHECKING:
    from api_harness import ApiDb
    from suitest_db.models.user import User
    from suitest_db.models.workspace import Workspace


def _h(ws_id: str) -> dict[str, str]:
    return {"X-Workspace-Id": ws_id}


async def _admin_ws(api_db: ApiDb, *, email: str, slug: str) -> tuple[User, Workspace]:
    user = await api_db.seed_user(email=email)
    ws = await api_db.seed_workspace(slug=slug, name=slug)
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.OWNER)
    return user, ws


@pytest.mark.asyncio
async def test_get_returns_404_when_unset(api_db: ApiDb) -> None:
    user, ws = await _admin_ws(api_db, email="llm-none@example.com", slug="llm-none")
    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/workspaces/{ws.id}/llm-config", headers=_h(ws.id))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_put_mock_sets_active_and_flips_tier(api_db: ApiDb) -> None:
    user, ws = await _admin_ws(api_db, email="llm-set@example.com", slug="llm-set")
    async with api_db.client(user) as c:
        put = await c.put(
            f"/api/v1/workspaces/{ws.id}/llm-config",
            headers=_h(ws.id),
            json={"provider": "mock", "model": "mock-1"},
        )
        assert put.status_code == 200, put.text
        body = put.json()
        assert body["provider"] == "mock"
        assert body["isActive"] is True
        assert body["tier"] == "CLOUD"
        assert body["apiKeyHint"] is None

        # M3-3: /capabilities reflects the new tier for this workspace.
        caps = await c.get("/capabilities", headers=_h(ws.id))
        assert caps.json()["tier"] == "CLOUD"
        assert caps.json()["features"]["ai_generation"] is True


@pytest.mark.asyncio
async def test_key_is_write_only_returns_hint(api_db: ApiDb) -> None:
    user, ws = await _admin_ws(api_db, email="llm-key@example.com", slug="llm-key")
    async with api_db.client(user) as c:
        put = await c.put(
            f"/api/v1/workspaces/{ws.id}/llm-config",
            headers=_h(ws.id),
            json={"provider": "openai", "model": "gpt-4o", "apiKey": "sk-secret-1234567890"},
        )
        assert put.status_code == 200, put.text
        assert "sk-secret" not in put.text
        assert put.json()["apiKeyHint"] == "sk-s…7890"


@pytest.mark.asyncio
async def test_put_cloud_without_key_is_422(api_db: ApiDb) -> None:
    user, ws = await _admin_ws(api_db, email="llm-nokey@example.com", slug="llm-nokey")
    async with api_db.client(user) as c:
        put = await c.put(
            f"/api/v1/workspaces/{ws.id}/llm-config",
            headers=_h(ws.id),
            json={"provider": "anthropic", "model": "claude-sonnet-4-5"},
        )
    assert put.status_code == 422
    assert put.json()["detail"]["code"] == "MISSING_API_KEY"


@pytest.mark.asyncio
async def test_test_connection_mock_ok(api_db: ApiDb) -> None:
    user, ws = await _admin_ws(api_db, email="llm-test@example.com", slug="llm-test")
    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/workspaces/{ws.id}/llm-config/test",
            headers=_h(ws.id),
            json={"provider": "mock", "model": "mock-1"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["modelEcho"] == "mock-1"


@pytest.mark.asyncio
async def test_delete_clears_and_downgrades_to_zero(api_db: ApiDb) -> None:
    user, ws = await _admin_ws(api_db, email="llm-del@example.com", slug="llm-del")
    async with api_db.client(user) as c:
        await c.put(
            f"/api/v1/workspaces/{ws.id}/llm-config",
            headers=_h(ws.id),
            json={"provider": "mock", "model": "mock-1"},
        )
        delete = await c.delete(f"/api/v1/workspaces/{ws.id}/llm-config", headers=_h(ws.id))
        assert delete.status_code == 204
        caps = await c.get("/capabilities", headers=_h(ws.id))
        assert caps.json()["tier"] == "ZERO"
        assert caps.json()["features"]["ai_generation"] is False
        gone = await c.get(f"/api/v1/workspaces/{ws.id}/llm-config", headers=_h(ws.id))
        assert gone.status_code == 404


@pytest.mark.asyncio
async def test_models_catalog_for_provider(api_db: ApiDb) -> None:
    user, ws = await _admin_ws(api_db, email="llm-models@example.com", slug="llm-models")
    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/workspaces/{ws.id}/llm-config/models",
            headers=_h(ws.id),
            params={"provider": "anthropic"},
        )
    assert resp.status_code == 200
    assert any(m["id"] == "claude-sonnet-4-5" for m in resp.json()["models"])


@pytest.mark.asyncio
async def test_non_admin_cannot_write(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="llm-qa@example.com")
    ws = await api_db.member_workspace(user, slug="llm-qa")  # default Role.QA
    async with api_db.client(user) as c:
        put = await c.put(
            f"/api/v1/workspaces/{ws.id}/llm-config",
            headers=_h(ws.id),
            json={"provider": "mock", "model": "mock-1"},
        )
    assert put.status_code == 403
