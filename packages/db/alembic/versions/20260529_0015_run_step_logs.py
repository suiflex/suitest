"""add run_step_logs table for persisted log streaming

Revision ID: 0015_run_step_logs
Revises: 0014_public_id_function
Create Date: 2026-05-29 00:00:00.000000

M1c Task 17 — persists the live log stream the orchestrator publishes to
Redis so the runs UI can paginate historical lines via cursor (``seq``)
without depending on Redis retention. ``seq`` is a per-run monotonic
counter the orchestrator maintains via Redis ``INCR run:<id>:logseq``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0015_run_step_logs"
down_revision: str | None = "0014_public_id_function"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_step_logs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_step_id",
            sa.String(32),
            sa.ForeignKey("run_steps.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("seq", sa.BigInteger, nullable=False),
        sa.Column("level", sa.String(16), nullable=False, server_default="info"),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Index("ix_run_step_logs_run_seq", "run_id", "seq"),
    )


def downgrade() -> None:
    op.drop_table("run_step_logs")
