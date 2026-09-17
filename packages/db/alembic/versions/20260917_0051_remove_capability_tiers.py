"""Remove Suitest capability tiers and legacy no-LLM validation fields.

Revision ID: 0051_remove_capability_tiers
Revises: 0050_case_diff_threshold
Create Date: 2026-09-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0051_remove_capability_tiers"
down_revision: str | None = "0050_case_diff_threshold"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_index("ix_runs_tier", table_name="runs")
    op.drop_column("runs", "tier_at_runtime")
    op.drop_index("ix_workspace_capabilities_tier", table_name="workspace_capabilities")
    op.drop_column("workspace_capabilities", "tier")
    op.drop_column("workspaces", "strict_zero_validation")
    if op.get_bind().dialect.name == "postgresql":
        postgresql.ENUM(name="tier").drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        tier: sa.types.TypeEngine[object] = postgresql.ENUM(
            "ZERO", "LOCAL", "CLOUD", name="tier", create_type=False
        )
        postgresql.ENUM("ZERO", "LOCAL", "CLOUD", name="tier").create(bind, checkfirst=True)
    else:
        tier = sa.Enum("ZERO", "LOCAL", "CLOUD", name="tier")

    op.add_column(
        "workspace_capabilities",
        sa.Column("tier", tier, nullable=False, server_default="ZERO"),
    )
    op.create_index(
        "ix_workspace_capabilities_tier", "workspace_capabilities", ["tier"], unique=False
    )
    op.add_column(
        "runs",
        sa.Column("tier_at_runtime", tier, nullable=False, server_default="ZERO"),
    )
    op.create_index("ix_runs_tier", "runs", ["tier_at_runtime"], unique=False)
    op.add_column(
        "workspaces",
        sa.Column("strict_zero_validation", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
