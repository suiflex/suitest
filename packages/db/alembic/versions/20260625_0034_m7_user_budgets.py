"""m7 user_budgets — per-user LLM spend caps (M7-1).

Revision ID: 0034_m7_user_budgets
Revises: 0032_m5_prompt_experiments
Create Date: 2026-06-25 00:00:00.000000

Creates the ``user_budgets`` table: per-user daily/monthly LLM spend caps
scoped to a workspace.  A value of 0 means "unlimited".

Maps to ``suitest_db.models.user_budget.UserBudget``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0034_m7_user_budgets"
down_revision: str | None = "0033_m6_diff_selection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_budgets",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "daily_cap_usd",
            sa.Numeric(precision=10, scale=4),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "monthly_cap_usd",
            sa.Numeric(precision=10, scale=4),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_budgets_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_user_budgets_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_budgets"),
        sa.UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_user_budgets_workspace_user",
        ),
    )
    op.create_index(
        "ix_user_budgets_workspace_id",
        "user_budgets",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_user_budgets_workspace_id", table_name="user_budgets")
    op.drop_table("user_budgets")
