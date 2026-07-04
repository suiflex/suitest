"""document_chunks: drop the unused pgvector ``embedding`` column.

The column shipped with 0011 for the planned RAG-to-LLM pipeline
(CAPABILITY_TIERS §5), but no code path ever wrote or queried it — semantic
test-case search (M4-2) embeds on demand and does not persist vectors. The RAG
design itself was superseded by the agent-first flow: the IDE coding agent reads
repo/PRD context directly, so server-side retrieval is no longer planned.

The ``vector`` extension created in 0001/0011 is left in place (idempotent,
already applied everywhere); removing it from the chain is deferred to the
SQLite/local-first work, which reworks dialect assumptions anyway.

Revision ID: 0045_drop_chunk_embedding
Revises: 0044_test_case_title_slug
Create Date: 2026-07-04
"""

from __future__ import annotations

from alembic import op

revision: str = "0045_drop_chunk_embedding"
down_revision: str | None = "0044_test_case_title_slug"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding")


def downgrade() -> None:
    # Restore the variable-dim column exactly as 0011 created it. Data is not
    # recoverable (nothing ever wrote to it).
    op.execute("ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding vector")
