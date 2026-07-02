"""Integration tests for the workspace file store (``/api/v1/files``).

Exercises the REAL auth path these endpoints are built for — an ``sk_suitest_``
API key (what the lifecycle/MCP publisher uses) — not a session. Asserts:

* POST stores a blob → returns its s3:// URL + workspace-scoped key.
* GET /files/signed-url signs an OWNED key; a key outside the workspace → 404.
* DELETE removes an owned key; out-of-scope key → 404 and never hits storage.

Object storage is monkeypatched so the tests never touch a real S3/MinIO — the
point is the router contract + the workspace-isolation guard, not aioboto3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_api.services import file_storage
from suitest_api.services.api_key_service import create_api_key
from suitest_shared.domain.enums import Role

if TYPE_CHECKING:
    from api_harness import ApiDb
    from suitest_db.models.workspace import Workspace


async def _key_for(api_db: ApiDb, *, email: str, slug: str) -> tuple[Workspace, dict[str, str]]:
    """Seed an owner + workspace and mint an API key; return (ws, auth headers)."""
    user = await api_db.seed_user(email=email)
    ws = await api_db.seed_workspace(slug=slug, name=slug)
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.OWNER)
    async with api_db.maker() as session:
        _, token = await create_api_key(
            session, workspace_id=ws.id, user_id=str(user.id), name="files-test"
        )
        await session.commit()
    return ws, {"X-API-Key": token}


@pytest.mark.asyncio
async def test_upload_stores_and_returns_url(
    api_db: ApiDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, auth = await _key_for(api_db, email="files-up@example.com", slug="files-up")
    key = f"uploads/{ws.id}/deadbeef/clip.webm"

    async def fake_upload(
        *, workspace_id: str, filename: str, data: bytes, content_type: str
    ) -> tuple[str, str, int]:
        assert workspace_id == ws.id
        return f"s3://bucket/{key}", key, len(data)

    monkeypatch.setattr(file_storage, "upload", fake_upload)

    async with api_db.client(None) as c:
        resp = await c.post(
            "/api/v1/files",
            headers=auth,
            files={"file": ("clip.webm", b"hello-bytes", "video/webm")},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["url"] == f"s3://bucket/{key}"
    assert body["key"] == key
    assert body["sizeBytes"] == len(b"hello-bytes")
    assert body["mimeType"] == "video/webm"


@pytest.mark.asyncio
async def test_upload_rejects_empty(api_db: ApiDb) -> None:
    _, auth = await _key_for(api_db, email="files-empty@example.com", slug="files-empty")
    async with api_db.client(None) as c:
        resp = await c.post(
            "/api/v1/files",
            headers=auth,
            files={"file": ("empty.png", b"", "image/png")},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_sign_owned_key_but_reject_cross_workspace(
    api_db: ApiDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, auth = await _key_for(api_db, email="files-sign@example.com", slug="files-sign")

    async def fake_presign(key: str) -> str:
        return f"https://signed.example/{key}?sig=stub"

    monkeypatch.setattr(file_storage, "presign_get", fake_presign)

    async with api_db.client(None) as c:
        ok = await c.get(
            "/api/v1/files/signed-url",
            headers=auth,
            params={"key": f"uploads/{ws.id}/abc/shot.png"},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["url"].startswith("https://signed.example/")

        cross = await c.get(
            "/api/v1/files/signed-url",
            headers=auth,
            params={"key": "uploads/some-other-ws/abc/shot.png"},
        )
        assert cross.status_code == 404


@pytest.mark.asyncio
async def test_delete_owned_and_reject_cross_workspace(
    api_db: ApiDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, auth = await _key_for(api_db, email="files-del@example.com", slug="files-del")
    deleted: list[str] = []

    async def fake_delete(key: str) -> None:
        deleted.append(key)

    monkeypatch.setattr(file_storage, "delete", fake_delete)

    own_key = f"uploads/{ws.id}/abc/shot.png"
    async with api_db.client(None) as c:
        gone = await c.request("DELETE", "/api/v1/files", headers=auth, params={"key": own_key})
        assert gone.status_code == 204
        assert deleted == [own_key]

        cross = await c.request(
            "DELETE",
            "/api/v1/files",
            headers=auth,
            params={"key": "uploads/other-ws/abc/shot.png"},
        )
        assert cross.status_code == 404
    assert deleted == [own_key]
