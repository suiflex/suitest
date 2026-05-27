"""add audit log table

Revision ID: 0012_audit_logs
Revises: 0011_documents
Create Date: 2026-05-27 00:00:09.000000

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0012_audit_logs"
down_revision: str | None = "0011_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", GUID(), nullable=True),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_audit_logs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_audit_logs_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(
        "ix_audit_logs_workspace_created",
        "audit_logs",
        ["workspace_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_workspace_created", table_name="audit_logs")
    op.drop_table("audit_logs")
