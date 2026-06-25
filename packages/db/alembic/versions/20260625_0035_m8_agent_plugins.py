"""m8 agent_definitions — workspace-scoped custom agent plugin definitions (M8-1..3)

Revision ID: 0035_m8_agent_plugins
Revises: 0032_m5_prompt_experiments
Create Date: 2026-06-25 00:00:00.000000

Adds ``agent_definitions`` table.  Each row stores the raw YAML spec for a
workspace-registered custom agent plugin (name, version, prompt, tool whitelist,
model preference, tier gate).  Soft-delete via ``is_active``; partial unique
index prevents duplicate active names per workspace while preserving history.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0035_m8_agent_plugins"
down_revision: str | None = "0034_m7_user_budgets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_definitions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("spec_yaml", sa.Text(), nullable=False),
        sa.Column("spec_version", sa.String(length=32), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_definitions_workspace_id",
        "agent_definitions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_agent_definitions_name",
        "agent_definitions",
        ["name"],
    )
    # Partial unique index: only one active definition per (workspace, name).
    op.execute(
        """
        CREATE UNIQUE INDEX uq_agent_definitions_workspace_active_name
        ON agent_definitions (workspace_id, name)
        WHERE is_active = true
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_agent_definitions_workspace_active_name")
    op.drop_index("ix_agent_definitions_name", table_name="agent_definitions")
    op.drop_index("ix_agent_definitions_workspace_id", table_name="agent_definitions")
    op.drop_table("agent_definitions")
