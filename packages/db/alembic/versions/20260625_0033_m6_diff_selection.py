"""m6 diff_selection — no persistent schema change (M6-1)

Revision ID: 0033_m6_diff_selection
Revises: 0032_m5_prompt_experiments
Create Date: 2026-06-25 00:00:00.000000

M6 diff-aware test selection is entirely request-scoped; there are no new
tables, columns, or indices required.  This migration is a no-op placeholder
that keeps the Alembic revision chain intact so the M6 milestone has a
trackable DB entry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0033_m6_diff_selection"
down_revision: str | None = "0032_m5_prompt_experiments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No schema changes — M6 state is ephemeral (request-scoped)."""


def downgrade() -> None:
    """No schema changes to revert."""
