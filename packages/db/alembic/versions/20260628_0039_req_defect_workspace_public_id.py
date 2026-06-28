"""requirements + defects: per-workspace public_id (dogfood blocker #3, finish).

Completes the systemic fix (see 0037 test_cases, 0038 runs). ``requirements``
gains a ``workspace_id`` (backfilled from the project); ``defects`` already has
one. Both swap the global ``public_id`` unique for a composite
``(workspace_id, public_id)``.

Revision ID: 0039_req_defect_ws_public_id
Revises: 0038_runs_ws_public_id
Create Date: 2026-06-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0039_req_defect_ws_public_id"
down_revision: str | None = "0038_runs_ws_public_id"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # requirements: add workspace_id (backfill from project), swap unique.
    op.add_column("requirements", sa.Column("workspace_id", sa.String(length=32), nullable=True))
    op.execute(
        """
        UPDATE requirements AS r
        SET workspace_id = p.workspace_id
        FROM projects AS p
        WHERE p.id = r.project_id
        """
    )
    op.alter_column("requirements", "workspace_id", nullable=False)
    op.create_foreign_key(
        "fk_requirements_workspace_id_workspaces",
        "requirements",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_requirements_public_id", "requirements", type_="unique")
    op.create_unique_constraint(
        "uq_requirements_workspace_public_id",
        "requirements",
        ["workspace_id", "public_id"],
    )

    # defects: already carries workspace_id — just swap the unique.
    op.drop_constraint("uq_defects_public_id", "defects", type_="unique")
    op.create_unique_constraint(
        "uq_defects_workspace_public_id",
        "defects",
        ["workspace_id", "public_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_defects_workspace_public_id", "defects", type_="unique")
    op.create_unique_constraint("uq_defects_public_id", "defects", ["public_id"])

    op.drop_constraint("uq_requirements_workspace_public_id", "requirements", type_="unique")
    op.create_unique_constraint("uq_requirements_public_id", "requirements", ["public_id"])
    op.drop_constraint(
        "fk_requirements_workspace_id_workspaces", "requirements", type_="foreignkey"
    )
    op.drop_column("requirements", "workspace_id")
