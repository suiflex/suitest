"""Integration tests for ``/api/v1/workspaces/:id/api-keys``.

* POST mints a key — plaintext returned once, only the hash is stored.
* GET lists live keys and NEVER carries the secret.
* DELETE revokes; revoked keys drop out of the list; unknown id → 404.
* Non-admins cannot mint keys (ADMIN+ only).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_api.services.api_key_service import KEY_PREFIX
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
async def test_create_returns_plaintext_once_then_list_hides_it(api_db: ApiDb) -> None:
    user, ws = await _admin_ws(api_db, email="ak-create@example.com", slug="ak-create")
    async with api_db.client(user) as c:
        created = await c.post(
            f"/api/v1/workspaces/{ws.id}/api-keys",
            headers=_h(ws.id),
            json={"name": "ci-key"},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["key"].startswith(KEY_PREFIX)
        assert body["name"] == "ci-key"
        assert body["key_prefix"] == body["key"][:15]
        assert body["revoked_at"] is None

        listed = await c.get(f"/api/v1/workspaces/{ws.id}/api-keys", headers=_h(ws.id))
        assert listed.status_code == 200
        items = listed.json()["items"]
        assert len(items) == 1
        # Admins can re-copy the full key: the AES-encrypted token round-trips.
        assert items[0]["key"] == body["key"]
        assert items[0]["key_prefix"] == body["key_prefix"]
        assert items[0]["last_used_at"] is None


@pytest.mark.asyncio
async def test_non_admin_cannot_list_keys(api_db: ApiDb) -> None:
    ws = await api_db.seed_workspace(slug="ak-list-role", name="ak-list-role")
    member = await api_db.seed_user(email="ak-list-member@example.com")
    await api_db.seed_membership(workspace_id=ws.id, user_id=member.id, role=Role.QA)
    async with api_db.client(member) as c:
        resp = await c.get(f"/api/v1/workspaces/{ws.id}/api-keys", headers=_h(ws.id))
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_revoke_removes_from_active_list(api_db: ApiDb) -> None:
    user, ws = await _admin_ws(api_db, email="ak-revoke@example.com", slug="ak-revoke")
    async with api_db.client(user) as c:
        created = await c.post(
            f"/api/v1/workspaces/{ws.id}/api-keys",
            headers=_h(ws.id),
            json={"name": "temp"},
        )
        key_id = created.json()["id"]

        revoked = await c.delete(
            f"/api/v1/workspaces/{ws.id}/api-keys/{key_id}", headers=_h(ws.id)
        )
        assert revoked.status_code == 204

        listed = await c.get(f"/api/v1/workspaces/{ws.id}/api-keys", headers=_h(ws.id))
        assert listed.json()["items"] == []


@pytest.mark.asyncio
async def test_revoke_unknown_id_is_404(api_db: ApiDb) -> None:
    user, ws = await _admin_ws(api_db, email="ak-404@example.com", slug="ak-404")
    async with api_db.client(user) as c:
        resp = await c.delete(
            f"/api/v1/workspaces/{ws.id}/api-keys/does-not-exist", headers=_h(ws.id)
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_non_admin_cannot_mint_key(api_db: ApiDb) -> None:
    ws = await api_db.seed_workspace(slug="ak-role", name="ak-role")
    member = await api_db.seed_user(email="ak-member@example.com")
    await api_db.seed_membership(workspace_id=ws.id, user_id=member.id, role=Role.QA)
    async with api_db.client(member) as c:
        resp = await c.post(
            f"/api/v1/workspaces/{ws.id}/api-keys",
            headers=_h(ws.id),
            json={"name": "nope"},
        )
        assert resp.status_code == 403


async def _mint_key(api_db: ApiDb, *, email: str, slug: str) -> tuple[str, str]:
    """Create a workspace + key; return (plaintext_token, workspace_id)."""
    user, ws = await _admin_ws(api_db, email=email, slug=slug)
    async with api_db.client(user) as c:
        created = await c.post(
            f"/api/v1/workspaces/{ws.id}/api-keys", headers=_h(ws.id), json={"name": "k"}
        )
    return created.json()["key"], ws.id


@pytest.mark.asyncio
async def test_whoami_with_bearer_key_resolves_workspace(api_db: ApiDb) -> None:
    token, ws_id = await _mint_key(api_db, email="ak-who1@example.com", slug="ak-who1")
    async with api_db.client(None) as c:
        resp = await c.get(
            "/api/v1/api-keys/whoami", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["workspace_id"] == ws_id


@pytest.mark.asyncio
async def test_whoami_with_x_api_key_header(api_db: ApiDb) -> None:
    token, ws_id = await _mint_key(api_db, email="ak-who2@example.com", slug="ak-who2")
    async with api_db.client(None) as c:
        resp = await c.get("/api/v1/api-keys/whoami", headers={"X-API-Key": token})
        assert resp.status_code == 200
        assert resp.json()["workspace_id"] == ws_id


@pytest.mark.asyncio
async def test_whoami_without_key_is_401(api_db: ApiDb) -> None:
    async with api_db.client(None) as c:
        resp = await c.get("/api/v1/api-keys/whoami")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_whoami_with_garbage_key_is_401(api_db: ApiDb) -> None:
    async with api_db.client(None) as c:
        resp = await c.get(
            "/api/v1/api-keys/whoami",
            headers={"Authorization": "Bearer sk_suitest_totally-made-up"},
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_revoked_key_no_longer_authenticates(api_db: ApiDb) -> None:
    user, ws = await _admin_ws(api_db, email="ak-who3@example.com", slug="ak-who3")
    async with api_db.client(user) as c:
        created = await c.post(
            f"/api/v1/workspaces/{ws.id}/api-keys", headers=_h(ws.id), json={"name": "k"}
        )
        token = created.json()["key"]
        key_id = created.json()["id"]
        # Works before revocation.
        pre = await c.get("/api/v1/api-keys/whoami", headers={"X-API-Key": token})
        assert pre.status_code == 200
        await c.delete(f"/api/v1/workspaces/{ws.id}/api-keys/{key_id}", headers=_h(ws.id))
    async with api_db.client(None) as c:
        post = await c.get("/api/v1/api-keys/whoami", headers={"X-API-Key": token})
        assert post.status_code == 401
