"""m5 prompt_experiments for prompt A/B testing (M5-4)

Revision ID: 0032_m5_prompt_experiments
Revises: 0031_workspace_prompts
Create Date: 2026-06-03 00:00:02.000000

Adds ``prompt_experiments`` — an A/B test between two prompt variants (file
default or a ``workspace_prompt_overrides`` fork) for one prompt in one
workspace. Mirrors ``packages/db/src/suitest_db/models/prompt_experiment.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0032_m5_prompt_experiments"
down_revision: str | None = "0031_workspace_prompts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_experiments",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("prompt_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("variant_a_override_id", sa.String(length=32), nullable=True),
        sa.Column("variant_b_override_id", sa.String(length=32), nullable=True),
        sa.Column("split_pct", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("a_impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("a_successes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("b_impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("b_successes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["variant_a_override_id"], ["workspace_prompt_overrides.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["variant_b_override_id"], ["workspace_prompt_overrides.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_prompt_experiments_active",
        "prompt_experiments",
        ["workspace_id", "prompt_name", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_prompt_experiments_active", table_name="prompt_experiments")
    op.drop_table("prompt_experiments")
