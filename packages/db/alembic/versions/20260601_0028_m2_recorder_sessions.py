"""m2 recorder_sessions table for the live browser recorder (M2-2)

Revision ID: 0028_m2_recorder_sessions
Revises: 0027_m1e_auth_invites
Create Date: 2026-06-01 00:00:00.000000

Adds the ``recorder_sessions`` table backing the live Playwright-MCP browser
recorder (M2 Task 4). ``generator_runs`` and ``code_exports`` already exist in
the chain (revision ``0012_audit_logs``) so this migration adds ONLY the
recorder table.

Columns mirror ``packages/db/src/suitest_db/models/recorder_session.py``:

* ``id`` — cuid2 text PK (``String(32)`` to match the rest of the schema).
* ``workspace_id`` — FK→workspaces ``ON DELETE CASCADE`` (tenant boundary).
* ``user_id`` — nullable FK→users (the human who opened the session).
* ``project_id`` — FK→projects (recorder cases land under a project's suite).
* ``captured_events_json`` — jsonb event log, defaults to ``[]``.
* ``status`` — ``active`` / ``finalized`` / ``cancelled`` / ``expired``.
* ``expires_at`` — TTL; a partial index keeps the idle-sweep query cheap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0028_m2_recorder_sessions"
down_revision: str | None = "0027_m1e_auth_invites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recorder_sessions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("start_url", sa.Text(), nullable=False),
        sa.Column(
            "mcp_provider",
            sa.String(length=64),
            nullable=False,
            server_default="playwright-mcp",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "captured_events_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("ws_room", sa.String(length=120), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_case_id", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["finalized_case_id"], ["test_cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recorder_sessions_workspace_status",
        "recorder_sessions",
        ["workspace_id", "status"],
    )
    op.create_index(
        "ix_recorder_sessions_expires_at",
        "recorder_sessions",
        ["expires_at"],
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("ix_recorder_sessions_expires_at", table_name="recorder_sessions")
    op.drop_index("ix_recorder_sessions_workspace_status", table_name="recorder_sessions")
    op.drop_table("recorder_sessions")
