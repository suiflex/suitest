"""add integrations with AES-GCM-encrypted secrets column

Revision ID: 0009_integrations
Revises: 0008_defects
Create Date: 2026-05-27 00:00:06.000000

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0009_integrations"
down_revision: str | None = "0008_defects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

integration_kind = postgresql.ENUM(
    "GITHUB",
    "GITLAB",
    "JENKINS",
    "JIRA",
    "LINEAR",
    "SLACK",
    "MCP_BROWSER_USE",
    "MCP_PLAYWRIGHT",
    "MCP_CUSTOM",
    "OPENAPI",
    "MCP_API",
    "MCP_POSTGRES",
    "MCP_KUBERNETES",
    "MCP_GRAPHQL",
    "MCP_GRPC",
    "MCP_APPIUM",
    "MCP_MONGO",
    "MCP_MYSQL",
    name="integration_kind",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    integration_kind.create(bind, checkfirst=True)

    op.create_table(
        "integrations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("kind", integration_kind, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("secrets_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_integrations_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integrations")),
    )
    op.create_index(
        "ix_integrations_workspace_kind", "integrations", ["workspace_id", "kind"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_integrations_workspace_kind", table_name="integrations")
    op.drop_table("integrations")
    integration_kind.drop(op.get_bind(), checkfirst=True)
