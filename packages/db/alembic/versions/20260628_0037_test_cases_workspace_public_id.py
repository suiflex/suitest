"""test_cases: per-workspace public_id uniqueness (dogfood blocker #3).

``public_id`` was globally unique but generated per-workspace (each workspace
mints its own ``TC-N`` sequence), so the first case in any 2nd+ workspace
collided on ``TC-1``. This adds ``test_cases.workspace_id`` (backfilled from the
suite -> project chain) and swaps the global unique for a composite
``(workspace_id, public_id)`` so each workspace owns its own sequence.

Revision ID: 0037_test_cases_ws_public_id
Revises: 0036_m9_plugin_registry
Create Date: 2026-06-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0037_test_cases_ws_public_id"
down_revision: str | None = "0036_m9_plugin_registry"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 1. Add the column nullable, backfill from suite -> project -> workspace.
    op.add_column("test_cases", sa.Column("workspace_id", sa.String(length=32), nullable=True))
    op.execute(
        """
        UPDATE test_cases AS tc
        SET workspace_id = p.workspace_id
        FROM suites AS s
        JOIN projects AS p ON p.id = s.project_id
        WHERE s.id = tc.suite_id
        """
    )
    op.alter_column("test_cases", "workspace_id", nullable=False)
    op.create_foreign_key(
        "fk_test_cases_workspace_id_workspaces",
        "test_cases",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 2. Swap the global unique for a per-workspace composite unique.
    op.drop_constraint("uq_test_cases_public_id", "test_cases", type_="unique")
    op.create_unique_constraint(
        "uq_test_cases_workspace_public_id",
        "test_cases",
        ["workspace_id", "public_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_test_cases_workspace_public_id", "test_cases", type_="unique")
    op.create_unique_constraint("uq_test_cases_public_id", "test_cases", ["public_id"])
    op.drop_constraint("fk_test_cases_workspace_id_workspaces", "test_cases", type_="foreignkey")
    op.drop_column("test_cases", "workspace_id")
