"""m5 workspace_prompt_overrides for per-workspace prompt forks (M5-3)

Revision ID: 0031_m5_workspace_prompt_overrides
Revises: 0030_m5_run_step_state_snapshot
Create Date: 2026-06-03 00:00:01.000000

Adds the ``workspace_prompt_overrides`` table — a DB-backed override layer on top
of the file-based default prompts (``suitest_agent.prompts.loader``). Mirrors
``packages/db/src/suitest_db/models/workspace_prompt_override.py``. One active
fork per ``(workspace_id, prompt_name)`` wins at resolution time; the file
default is the fallback so the ZERO/default path is untouched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0031_m5_workspace_prompt_overrides"
down_revision: str | None = "0030_m5_run_step_state_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_prompt_overrides",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("prompt_name", sa.String(length=120), nullable=False),
        sa.Column("base_version", sa.String(length=32), nullable=False),
        sa.Column("fork_version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "prompt_name",
            "fork_version",
            name="uq_workspace_prompt_overrides_ws_name_ver",
        ),
    )
    op.create_index(
        "ix_workspace_prompt_overrides_active",
        "workspace_prompt_overrides",
        ["workspace_id", "prompt_name", "is_active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_prompt_overrides_active",
        table_name="workspace_prompt_overrides",
    )
    op.drop_table("workspace_prompt_overrides")
