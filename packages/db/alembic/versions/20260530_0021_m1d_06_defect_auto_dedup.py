"""m1d 06 uq_defects_auto_dedup partial unique idx

Revision ID: 0021_m1d_06_defect_dedup
Revises: 0020_m1d_05_mcp_pins
Create Date: 2026-05-30 00:00:06.000000

Adds the partial unique index used by the M1d-10 auto-defect filer to dedup
system-created defects per ``(run_id, test_case_id)``. The predicate
``created_by = 'system'`` ensures human-filed defects can still repeat for
the same run+case combination (e.g. a QA filing both a UI bug and a backend
bug on the same failed step).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0021_m1d_06_defect_dedup"
down_revision: str | None = "0020_m1d_05_mcp_pins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_defects_auto_dedup",
        "defects",
        ["run_id", "test_case_id"],
        unique=True,
        postgresql_where=sa.text("created_by = 'system'"),
    )


def downgrade() -> None:
    op.drop_index("uq_defects_auto_dedup", table_name="defects")
