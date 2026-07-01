"""api_keys — programmatic API keys for MCP / SDK / CI access.

A workspace-scoped, hashed API key that lets an AI IDE's MCP client, the CLI, or
a CI job authenticate to the API without a human session. Only the SHA-256 hash
is stored; the plaintext token is shown once at creation.

Revision ID: 0042_api_keys
Revises: 0041_tcm_automation_review
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0042_api_keys"
down_revision: str | None = "0041_tcm_automation_review"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(length=32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("key_prefix", sa.String(length=20), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_api_keys_workspace", "api_keys", ["workspace_id"])
    op.create_index("ux_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_api_keys_key_hash", table_name="api_keys")
    op.drop_index("ix_api_keys_workspace", table_name="api_keys")
    op.drop_table("api_keys")
