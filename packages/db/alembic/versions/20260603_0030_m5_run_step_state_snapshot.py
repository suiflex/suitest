"""m5 run_steps.state_snapshot for time-travel diff viewer (M5-1)

Revision ID: 0030_m5_run_step_state_snapshot
Revises: 0029_m4_webhook_dispatch_attempts
Create Date: 2026-06-03 00:00:00.000000

Adds the nullable ``state_snapshot`` jsonb column to ``run_steps``. The runner
persists the normalized MCP tool output (``McpToolResult.output``) here after
each step so the time-travel replay endpoint can compute a deterministic
per-step state delta without any LLM (ZERO-tier compatible). Mirrors
``packages/db/src/suitest_db/models/run.py`` ``RunStep.state_snapshot``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0030_m5_run_step_state_snapshot"
down_revision: str | None = "0029_m4_webhook_dispatch_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "run_steps",
        sa.Column("state_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("run_steps", "state_snapshot")
