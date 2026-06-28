"""runs: per-workspace public_id uniqueness (dogfood blocker #3, runs).

Same fix as test_cases (0037): ``runs.public_id`` was globally unique but minted
per-workspace, so the first run in any 2nd+ workspace collided on ``R-1000``.
Adds ``runs.workspace_id`` (backfilled from the project) and swaps the global
unique for a composite ``(workspace_id, public_id)``.

Revision ID: 0038_runs_ws_public_id
Revises: 0037_test_cases_ws_public_id
Create Date: 2026-06-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0038_runs_ws_public_id"
down_revision: str | None = "0037_test_cases_ws_public_id"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("workspace_id", sa.String(length=32), nullable=True))
    op.execute(
        """
        UPDATE runs AS r
        SET workspace_id = p.workspace_id
        FROM projects AS p
        WHERE p.id = r.project_id
        """
    )
    op.alter_column("runs", "workspace_id", nullable=False)
    op.create_foreign_key(
        "fk_runs_workspace_id_workspaces",
        "runs",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_runs_public_id", "runs", type_="unique")
    op.create_unique_constraint(
        "uq_runs_workspace_public_id",
        "runs",
        ["workspace_id", "public_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_runs_workspace_public_id", "runs", type_="unique")
    op.create_unique_constraint("uq_runs_public_id", "runs", ["public_id"])
    op.drop_constraint("fk_runs_workspace_id_workspaces", "runs", type_="foreignkey")
    op.drop_column("runs", "workspace_id")
