"""Document read endpoints (docs/API.md §3.11) — workspace-scoped, paginated.

Documents carry ``workspace_id`` directly. Each row exposes a computed
``chunk_count`` (batched via one grouped query for the list); chunk bodies are not
returned in M1a.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.document import Document
from suitest_db.repositories.documents import DocumentRepo
from suitest_shared.domain.enums import DocumentKind
from suitest_shared.schemas.pagination import Page, PageMeta

from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.routers._pagination import decode_cursor_or_400, encode_next
from suitest_api.schemas.document import DocumentDetail, DocumentListItem

router = APIRouter(prefix="/api/v1", tags=["documents"])


def _list_item(row: Document, chunk_count: int) -> DocumentListItem:
    return DocumentListItem(
        id=row.id,
        workspace_id=row.workspace_id,
        kind=row.kind,
        source=row.source,
        title=row.title,
        content_hash=row.content_hash,
        chunk_count=chunk_count,
        indexed_at=row.indexed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/documents", response_model=Page[DocumentListItem])
async def list_documents(
    kind: DocumentKind | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> Page[DocumentListItem]:
    """List the workspace's indexed documents (optionally by kind), paginated."""
    repo = DocumentRepo(session)
    decoded = decode_cursor_or_400(cursor)
    rows, next_keyset = await repo.list_by_workspace(
        ctx.workspace_id, kind=kind, cursor=decoded, limit=limit
    )
    counts = await repo.chunk_counts([r.id for r in rows])
    return Page[DocumentListItem](
        items=[_list_item(r, counts.get(r.id, 0)) for r in rows],
        meta=PageMeta(next_cursor=encode_next(next_keyset), limit=limit),
    )


@router.get("/documents/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> DocumentDetail:
    """Return one document with its chunk_count; 404 when cross-workspace."""
    repo = DocumentRepo(session)
    row = await repo.get_by_id(document_id)
    if row is None or row.workspace_id != ctx.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    counts = await repo.chunk_counts([row.id])
    base = _list_item(row, counts.get(row.id, 0))
    return DocumentDetail(**base.model_dump())
