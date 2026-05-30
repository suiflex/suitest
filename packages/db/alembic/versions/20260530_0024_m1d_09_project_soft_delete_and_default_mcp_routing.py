"""m1d 09 projects.deleted_at + projects.default_mcp_routing + partial idx

Revision ID: 0024_m1d_09_project_soft_delete
Revises: 0023_m1d_08_seed_bundled_mcp
Create Date: 2026-05-30 00:00:09.000000

Project-level changes required by M1d-5:

* ``projects.deleted_at`` — soft-delete tombstone driven by
  ``DELETE /projects/:id`` with ``confirmCascade=true`` and cleared by
  ``POST /projects/:id/restore``. List endpoints filter
  ``deleted_at IS NULL`` by default.
* ``projects.default_mcp_routing`` — project-scoped MCP override map
  (precedes workspace override at resolve time per ``MCP_PLUGINS §4.1``).
  Same shape as ``workspaces.mcp_routing_overrides``: a JSONB dict mapping
  ``target_kind`` -> ``mcp_provider`` name. Defaults to ``{}``.
* Partial index ``ix_projects_workspace_active`` — covers the default
  active-list query (``WHERE workspace_id = ? AND deleted_at IS NULL``).
  30-day hard-purge sweeper is deferred to M2+.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0024_m1d_09_project_soft_delete"
down_revision: str | None = "0023_m1d_08_seed_bundled_mcp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column(
            "default_mcp_routing",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_projects_workspace_active",
        "projects",
        ["workspace_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_projects_workspace_active", table_name="projects")
    op.drop_column("projects", "default_mcp_routing")
    op.drop_column("projects", "deleted_at")
