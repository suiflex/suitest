"""m1d 01 workspaces.strict_zero_validation + workspaces.mcp_routing_overrides

Revision ID: 0016_m1d_01_workspace_flags
Revises: 0015_run_step_logs
Create Date: 2026-05-30 00:00:01.000000

First M1d migration. Adds two workspace-level toggles required by the manual
TCM write path (M1d-2 onwards):

* ``workspaces.strict_zero_validation`` — when true (default), the ZERO-tier
  validator rejects test steps lacking executable code per
  ``CAPABILITY_TIERS §6.3``. Flipping to false lets a workspace stage
  manual-only cases before a runner is configured.
* ``workspaces.mcp_routing_overrides`` — workspace-scoped override map keyed
  by ``target_kind`` → ``mcp_provider_name`` per ``MCP_PLUGINS §4.1``. Merged
  below the suite-level override (added in revision _02) at resolve time.

Both columns are additive with NOT NULL DEFAULTs so existing rows backfill
automatically; the downgrade drops them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0016_m1d_01_workspace_flags"
down_revision: str | None = "0015_run_step_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "strict_zero_validation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("'true'"),
        ),
    )
    op.add_column(
        "workspaces",
        sa.Column(
            "mcp_routing_overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "mcp_routing_overrides")
    op.drop_column("workspaces", "strict_zero_validation")
