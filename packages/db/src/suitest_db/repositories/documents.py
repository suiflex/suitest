"""Document repository with filtered keyset listing."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import func, select
from suitest_db.models.document import Document, DocumentChunk
from suitest_db.repositories.base import AsyncRepository
from suitest_shared.domain.enums import DocumentKind

if TYPE_CHECKING:
    from collections.abc import Sequence


class DocumentCreate(BaseModel):
    workspace_id: str
    kind: DocumentKind
    source: str
    title: str
    content_hash: str
    meta: dict[str, object] | None = None


class DocumentUpdate(BaseModel):
    title: str | None = None
    source: str | None = None
    content_hash: str | None = None
    indexed_at: datetime | None = None
    meta: dict[str, object] | None = None


class DocumentRepo(AsyncRepository[Document, DocumentCreate, DocumentUpdate]):
    model = Document

    async def list_by_workspace(
        self,
        workspace_id: str,
        *,
        kind: DocumentKind | None = None,
        cursor: tuple[datetime, str] | None = None,
        limit: int = 20,
    ) -> tuple[Sequence[Document], tuple[datetime, str] | None]:
        stmt = select(Document).where(Document.workspace_id == workspace_id)
        if kind is not None:
            stmt = stmt.where(Document.kind == kind)
        if cursor is not None:
            cursor_ts, cursor_id = cursor
            stmt = stmt.where(
                (Document.created_at < cursor_ts)
                | ((Document.created_at == cursor_ts) & (Document.id < cursor_id))
            )
        stmt = stmt.order_by(Document.created_at.desc(), Document.id.desc()).limit(limit + 1)

        rows = list((await self.session.scalars(stmt)).all())
        if len(rows) > limit:
            page = rows[:limit]
            last = page[-1]
            next_cursor: tuple[datetime, str] | None = (last.created_at, last.id)
        else:
            page = rows
            next_cursor = None
        return page, next_cursor

    async def chunk_counts(self, document_ids: Sequence[str]) -> dict[str, int]:
        """Map each document id → its number of chunks (one grouped query)."""
        if not document_ids:
            return {}
        stmt = (
            select(DocumentChunk.document_id, func.count(DocumentChunk.id))
            .where(DocumentChunk.document_id.in_(document_ids))
            .group_by(DocumentChunk.document_id)
        )
        counts: dict[str, int] = {}
        for doc_id, count in (await self.session.execute(stmt)).all():
            counts[doc_id] = count
        return counts
