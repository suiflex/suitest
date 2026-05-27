"""Document + DocumentChunk models with variable-dim pgvector (docs/DATA_MODEL.md §3.10)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from suitest_shared.domain.enums import DocumentKind

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[DocumentKind] = mapped_column(
        SAEnum(DocumentKind, name="document_kind"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(1024), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (Index("ix_documents_workspace_kind", "workspace_id", "kind"),)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Variable dim — Vector(None) → no fixed dim. Per-workspace dim check constraint
    # is added in a later migration (DATA_MODEL §13). No M1a check yet.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(None))

    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

    __table_args__ = (
        Index("ix_document_chunks_document_id", "document_id"),
        # TODO(M1b+): per-workspace HNSW index added via raw-SQL migration
        # (DATA_MODEL §7.2): CREATE INDEX ... USING hnsw (embedding vector_cosine_ops).
    )
