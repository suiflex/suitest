"""init workspaces

Revision ID: 0001_init_workspaces
Revises:
Create Date: 2026-05-26 00:00:00.000000

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001_init_workspaces"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector extension (idempotent) — used in M1b for embeddings.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
        sa.UniqueConstraint("slug", name=op.f("uq_workspaces_slug")),
    )


def downgrade() -> None:
    op.drop_table("workspaces")
    # Note: we intentionally do NOT drop the vector extension on downgrade —
    # other migrations/tenants may depend on it.
