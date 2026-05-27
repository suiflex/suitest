"""add agent sessions, messages, and tool calls

Revision ID: 0010_agent
Revises: 0009_integrations
Create Date: 2026-05-27 00:00:07.000000

DEFERRED FK: ``agent_sessions.prompt_version_id`` is created here as a plain
nullable column WITHOUT its foreign-key constraint, because ``prompt_versions``
does not exist yet. The FK constraint is added in revision 0012 (after
``prompt_versions`` is created) via ``op.create_foreign_key`` — see
DATA_MODEL.md §10 rule 6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0010_agent"
down_revision: str | None = "0009_integrations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

agent_session_kind = postgresql.ENUM(
    "GENERATION",
    "EXECUTION",
    "DIAGNOSIS",
    "CONVERSATION",
    name="agent_session_kind",
    create_type=False,
)
message_role = postgresql.ENUM(
    "USER", "AGENT", "SYSTEM", "TOOL", name="message_role", create_type=False
)

_ENUMS = (agent_session_kind, message_role)


def upgrade() -> None:
    bind = op.get_bind()
    for enum in _ENUMS:
        enum.create(bind, checkfirst=True)

    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", agent_session_kind, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        # prompt_version_id: column only — FK constraint added in revision 0012.
        sa.Column("prompt_version_id", sa.String(length=32), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_agent_sessions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_agent_sessions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_sessions")),
    )
    op.create_index(
        "ix_agent_sessions_workspace_kind",
        "agent_sessions",
        ["workspace_id", "kind"],
        unique=False,
    )
    op.create_index("ix_agent_sessions_provider", "agent_sessions", ["provider"], unique=False)

    op.create_table(
        "agent_messages",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("role", message_role, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            name=op.f("fk_agent_messages_session_id_agent_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_messages")),
    )
    op.create_index("ix_agent_messages_session_id", "agent_messages", ["session_id"], unique=False)

    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.String(length=32), nullable=False),
        sa.Column("tool_name", sa.String(length=120), nullable=False),
        sa.Column("mcp_provider", sa.String(length=64), nullable=True),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["agent_messages.id"],
            name=op.f("fk_agent_tool_calls_message_id_agent_messages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_tool_calls")),
    )


def downgrade() -> None:
    op.drop_table("agent_tool_calls")
    op.drop_index("ix_agent_messages_session_id", table_name="agent_messages")
    op.drop_table("agent_messages")
    op.drop_index("ix_agent_sessions_provider", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_workspace_kind", table_name="agent_sessions")
    op.drop_table("agent_sessions")

    bind = op.get_bind()
    for enum in reversed(_ENUMS):
        enum.drop(bind, checkfirst=True)
