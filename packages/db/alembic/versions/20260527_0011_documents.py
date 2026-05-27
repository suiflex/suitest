"""add documents + chunks with variable-dim pgvector

Revision ID: 0011_documents
Revises: 0010_agent
Create Date: 2026-05-27 00:00:08.000000

The ``vector`` extension is created in revision 0001; this migration assumes it
exists. ``document_chunks.embedding`` uses ``Vector`` with NO fixed dimension
(variable dim). Per-workspace dim check constraints + HNSW index are added in a
later migration (DATA_MODEL.md §13 / §7.2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0011_documents"
down_revision: str | None = "0010_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

document_kind = postgresql.ENUM(
    "PRD",
    "OPENAPI",
    "URL_CRAWL",
    "LINEAR_ISSUE",
    "NOTION_PAGE",
    "CUSTOM",
    name="document_kind",
    create_type=False,
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    document_kind.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("kind", document_kind, nullable=False),
        sa.Column("source", sa.String(length=1024), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_documents_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(
        "ix_documents_workspace_kind", "documents", ["workspace_id", "kind"], unique=False
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("document_id", sa.String(length=32), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # Vector() with no dimension → variable-dim pgvector column.
        sa.Column("embedding", Vector(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_chunks_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunks")),
    )
    op.create_index(
        "ix_document_chunks_document_id", "document_chunks", ["document_id"], unique=False
    )
    # TODO(M1b+): per-workspace HNSW index on `embedding` via raw-SQL migration.


def downgrade() -> None:
    op.drop_index("ix_document_chunks_document_id", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_documents_workspace_kind", table_name="documents")
    op.drop_table("documents")
    document_kind.drop(op.get_bind(), checkfirst=True)
