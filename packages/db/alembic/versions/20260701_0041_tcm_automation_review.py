"""test_cases: automation review-status gate.

Phase 2b (deterministic translate + review gate). Adds:
  * ``automation_status`` — review state of ``automation_code``. NULL = no
    automation; ``draft`` = translated/generated, awaiting human review;
    ``approved`` = a human reviewed & pinned the code. The deterministic runner
    executes automation ONLY when this is ``approved``.
  * ``automation_reviewed_at`` / ``automation_reviewed_by`` — audit pointers for
    who approved the pinned code and when.

All columns are nullable; no backfill needed (existing cases have NULLs until a
translate/approve cycle runs).

Revision ID: 0041_tcm_automation_review
Revises: 0040_tcm_automation_lastrun
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0041_tcm_automation_review"
down_revision: str | None = "0040_tcm_automation_lastrun"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("test_cases", sa.Column("automation_status", sa.String(length=16), nullable=True))
    op.add_column(
        "test_cases",
        sa.Column("automation_reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "test_cases",
        sa.Column("automation_reviewed_by", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_test_cases_automation_reviewed_by_users",
        "test_cases",
        "users",
        ["automation_reviewed_by"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_test_cases_automation_reviewed_by_users", "test_cases", type_="foreignkey"
    )
    op.drop_column("test_cases", "automation_reviewed_by")
    op.drop_column("test_cases", "automation_reviewed_at")
    op.drop_column("test_cases", "automation_status")
