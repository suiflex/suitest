"""m1d 28 workspaces.deleted_at tombstone for slug-confirm DELETE

Revision ID: 0026_m1d_28_ws_soft_delete
Revises: 0025_m1d_10_req_soft_delete
Create Date: 2026-05-30 00:00:08.000000

``DELETE /workspaces/:id`` (OWNER-only, slug-typed-confirm) marks the workspace
``deleted_at = now()`` and enqueues an async ``workspace_cleanup`` ARQ job that
tears down MCP sessions, R2 artifacts, and child rows. Reads short-circuit when
``deleted_at IS NOT NULL`` so the FE Danger Zone confirm instantly hides the
workspace from list / detail before the background cleanup finishes.

Partial index ``ix_workspaces_active`` keeps the (very small) ``deleted_at IS
NULL`` working set hot so ``GET /workspaces`` and the membership join stay
keyset-fast even after a handful of historical workspaces accumulate tombstones.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0026_m1d_28_ws_soft_delete"
down_revision: str | None = "0025_m1d_10_req_soft_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_workspaces_active",
        "workspaces",
        ["id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_workspaces_active", table_name="workspaces")
    op.drop_column("workspaces", "deleted_at")
