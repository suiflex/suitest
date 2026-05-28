"""Document response DTOs (docs/API.md §3.11)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from suitest_shared.domain.enums import DocumentKind


class DocumentListItem(BaseModel):
    """List row for ``GET /documents`` with a computed ``chunk_count``."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    kind: DocumentKind
    source: str
    title: str
    content_hash: str
    chunk_count: int
    indexed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentListItem):
    """Detail for ``GET /documents/:id`` — no chunk bodies in M1a."""
