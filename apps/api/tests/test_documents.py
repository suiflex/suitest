"""Task 7h — document read endpoint tests (docs/API.md §3.11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.document import Document, DocumentChunk
from suitest_shared.domain.enums import DocumentKind

if TYPE_CHECKING:
    from api_harness import ApiDb


def _doc(ws_id: str, *, kind: DocumentKind, title: str, source: str = "https://x") -> Document:
    return Document(
        workspace_id=ws_id,
        kind=kind,
        source=source,
        title=title,
        content_hash="hash",
    )


@pytest.mark.asyncio
async def test_list_documents_filter_kind_prd(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="doc-list@example.com")
    ws = await api_db.member_workspace(user, slug="doc-list-ws")
    await api_db.add_all(
        [
            _doc(ws.id, kind=DocumentKind.PRD, title="PRD doc"),
            _doc(ws.id, kind=DocumentKind.OPENAPI, title="OpenAPI doc"),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/documents?kind=PRD", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert {d["title"] for d in items} == {"PRD doc"}


@pytest.mark.asyncio
async def test_document_detail_chunk_count(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="doc-chunk@example.com")
    ws = await api_db.member_workspace(user, slug="doc-chunk-ws")
    doc = _doc(ws.id, kind=DocumentKind.PRD, title="chunked")
    await api_db.add_all([doc])
    await api_db.add_all(
        [DocumentChunk(document_id=doc.id, chunk_index=i, content=f"chunk {i}") for i in range(4)]
    )
    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/documents/{doc.id}", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    assert resp.json()["chunk_count"] == 4


@pytest.mark.asyncio
async def test_get_document_404_cross_workspace(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="doc-x@example.com")
    ws = await api_db.member_workspace(user, slug="doc-x-ws")
    other = await api_db.seed_workspace(slug="doc-x-other", name="Other")
    doc = _doc(other.id, kind=DocumentKind.PRD, title="hidden")
    await api_db.add_all([doc])

    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/documents/{doc.id}", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 404
