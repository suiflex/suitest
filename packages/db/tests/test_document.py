"""Tests for documents + chunks with variable-dim pgvector (Task 2i)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.ids import new_id
from suitest_db.models.document import Document, DocumentChunk
from suitest_db.models.workspace import Workspace
from suitest_shared.domain.enums import DocumentKind


async def _document(session: AsyncSession) -> Document:
    ws = Workspace(slug=f"ws-{new_id()}", name="WS")
    session.add(ws)
    await session.flush()
    doc = Document(
        workspace_id=ws.id,
        kind=DocumentKind.PRD,
        source="file://prd.md",
        title="PRD",
        content_hash="abc123",
    )
    session.add(doc)
    await session.flush()
    return doc


@pytest.mark.asyncio
async def test_document_chunk_variable_dim(session: AsyncSession) -> None:
    doc = await _document(session)
    c384 = DocumentChunk(document_id=doc.id, chunk_index=0, content="a", embedding=[0.1] * 384)
    c1536 = DocumentChunk(document_id=doc.id, chunk_index=1, content="b", embedding=[0.1] * 1536)
    session.add_all([c384, c1536])
    await session.flush()  # both succeed — no fixed-dim constraint in M1a


@pytest.mark.asyncio
async def test_document_cascade_to_chunks(session: AsyncSession) -> None:
    doc = await _document(session)
    chunk = DocumentChunk(document_id=doc.id, chunk_index=0, content="a", embedding=[0.1] * 8)
    session.add(chunk)
    await session.flush()
    cid = chunk.id

    await session.delete(doc)
    await session.flush()
    session.expunge_all()
    assert await session.get(DocumentChunk, cid) is None
