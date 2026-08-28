"""Add per-case pixel-diff threshold override (M12-3).

Revision ID: 0050_case_diff_threshold
Revises: 0049_llm_config_oauth
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0050_case_diff_threshold"
down_revision: str | None = "0049_llm_config_oauth"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "test_cases",
        sa.Column("diff_threshold", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("test_cases", "diff_threshold")
