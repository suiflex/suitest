"""m1d 04 projects.gating_suite_id (FK suites ON DELETE SET NULL)

Revision ID: 0019_m1d_04_gating_suite
Revises: 0018_m1d_03_case_order
Create Date: 2026-05-30 00:00:04.000000

Adds an optional pinned smoke suite reference on each project. Used by:

* Webhook-triggered gating runs (M1d-16 / M1d-17 / M1d-18) — if the project
  has no gating suite, the webhook handler rejects with 422.
* The Dashboard "promote to gating" autopilot action (M1d-26).

Width is ``String(32)`` to match the actual ``suites.id`` width declared in
revision ``0004_projects_suites``. FK uses ``ON DELETE SET NULL`` so deleting
the underlying suite nulls the project pointer rather than cascading.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0019_m1d_04_gating_suite"
down_revision: str | None = "0018_m1d_03_case_order"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_NAME = "fk_projects_gating_suite_id_suites"


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("gating_suite_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        _FK_NAME,
        "projects",
        "suites",
        ["gating_suite_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_FK_NAME, "projects", type_="foreignkey")
    op.drop_column("projects", "gating_suite_id")
