"""m1d 02 suites.mcp_routing_overrides + suites.deleted_at + partial idx

Revision ID: 0017_m1d_02_suite_soft_delete
Revises: 0016_m1d_01_workspace_flags
Create Date: 2026-05-30 00:00:02.000000

Suite-level changes required by M1d-3 / M1d-4 / M1d-21:

* ``suites.mcp_routing_overrides`` — suite-scoped MCP override map; precedes
  workspace override at resolve time (``MCP_PLUGINS §4.1``).
* ``suites.deleted_at`` — soft-delete tombstone driven by
  ``DELETE /suites/:id`` with ``confirmCascade=true`` and cleared by
  ``POST /suites/:id/restore`` (M1d-4). List endpoints filter
  ``deleted_at IS NULL`` by default.
* Partial index ``ix_suites_project_active`` — covers the default active-list
  query (``WHERE project_id = ? AND deleted_at IS NULL``). 30-day hard-purge
  sweeper is deferred to M2+.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0017_m1d_02_suite_soft_delete"
down_revision: str | None = "0016_m1d_01_workspace_flags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "suites",
        sa.Column(
            "mcp_routing_overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "suites",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_suites_project_active",
        "suites",
        ["project_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_suites_project_active", table_name="suites")
    op.drop_column("suites", "deleted_at")
    op.drop_column("suites", "mcp_routing_overrides")
