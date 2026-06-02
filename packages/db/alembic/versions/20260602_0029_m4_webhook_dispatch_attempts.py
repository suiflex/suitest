"""m4 webhook_dispatch_attempts table for the external webhook retry queue (M4-31)

Revision ID: 0029_m4_webhook_dispatch_attempts
Revises: 0028_m2_recorder_sessions
Create Date: 2026-06-02 00:00:00.000000

Adds the durable retry ledger backing the M4-31
:class:`~suitest_api.services.webhook_retry_queue.WebhookRetryQueue`. One row
per logical outbound dispatch to an external integration (Jira / Linear /
GitHub / Slack / GitLab); deduped per-integration by ``idempotency_key`` so a
double-fire never doubles the upstream effect.

Columns mirror ``packages/db/src/suitest_db/models/webhook_dispatch.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0029_m4_webhook_dispatch_attempts"
down_revision: str | None = "0028_m2_recorder_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_dispatch_attempts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("integration_id", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempt_n", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["integration_id"], ["integrations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_webhook_dispatch_attempts"),
        sa.UniqueConstraint("integration_id", "idempotency_key", name="webhook_dedup"),
    )
    op.create_index(
        "ix_webhook_dispatch_attempts_status",
        "webhook_dispatch_attempts",
        ["status"],
    )
    op.create_index(
        "ix_webhook_dispatch_attempts_next_retry_at",
        "webhook_dispatch_attempts",
        ["next_retry_at"],
        postgresql_where=sa.text("status = 'failed'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_dispatch_attempts_next_retry_at",
        table_name="webhook_dispatch_attempts",
    )
    op.drop_index(
        "ix_webhook_dispatch_attempts_status",
        table_name="webhook_dispatch_attempts",
    )
    op.drop_table("webhook_dispatch_attempts")
