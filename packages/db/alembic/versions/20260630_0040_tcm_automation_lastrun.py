"""test_cases: automation file/code + denormalized last-run pointers.

Phase 2 (lifecycle ingest). Adds:
  * ``automation_file_path`` / ``automation_code`` — link a case to its exported
    runnable test file and persist the full generated source for the web Code tab.
  * ``last_run_id`` / ``last_run_result`` / ``last_run_at`` /
    ``last_failure_reason`` / ``last_duration_ms`` — denormalized "last run"
    fields the run-ingest service updates on every ingested run.

All columns are nullable; no backfill needed (existing cases simply have NULLs
until their next generation/ingest).

Revision ID: 0040_tcm_automation_lastrun
Revises: 0039_req_defect_ws_public_id
Create Date: 2026-06-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0040_tcm_automation_lastrun"
down_revision: str | None = "0039_req_defect_ws_public_id"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("test_cases", sa.Column("automation_file_path", sa.String(length=512), nullable=True))
    op.add_column("test_cases", sa.Column("automation_code", sa.Text(), nullable=True))
    op.add_column("test_cases", sa.Column("last_run_id", sa.String(length=32), nullable=True))
    op.add_column("test_cases", sa.Column("last_run_result", sa.String(length=16), nullable=True))
    op.add_column(
        "test_cases", sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("test_cases", sa.Column("last_failure_reason", sa.Text(), nullable=True))
    op.add_column("test_cases", sa.Column("last_duration_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("test_cases", "last_duration_ms")
    op.drop_column("test_cases", "last_failure_reason")
    op.drop_column("test_cases", "last_run_at")
    op.drop_column("test_cases", "last_run_result")
    op.drop_column("test_cases", "last_run_id")
    op.drop_column("test_cases", "automation_code")
    op.drop_column("test_cases", "automation_file_path")
