"""m1d 03 test_cases.order_in_suite + ix_test_cases_suite_order composite

Revision ID: 0018_m1d_03_case_order
Revises: 0017_m1d_02_suite_soft_delete
Create Date: 2026-05-30 00:00:03.000000

Adds a manual sort key on ``test_cases`` plus a composite ``(suite_id,
order_in_suite)`` index. Drives the suite drag-reorder UX (M1d-21/22) and the
deterministic runner's suite execution order. Default 0; service layer breaks
ties by ``created_at`` ASC.

Note: the single-column auto-named ``ix_test_cases_order_in_suite`` (emitted
by SQLAlchemy when ``index=True`` is set on the mapped column) is **not**
created here — plan-05b is explicit that we only add the composite index. The
ORM declaration omits ``index=True`` to match.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0018_m1d_03_case_order"
down_revision: str | None = "0017_m1d_02_suite_soft_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "test_cases",
        sa.Column(
            "order_in_suite",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_index(
        "ix_test_cases_suite_order",
        "test_cases",
        ["suite_id", "order_in_suite"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_test_cases_suite_order", table_name="test_cases")
    op.drop_column("test_cases", "order_in_suite")
