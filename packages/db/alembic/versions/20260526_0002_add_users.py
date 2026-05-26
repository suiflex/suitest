"""add users + oauth_accounts

Revision ID: 0002_add_users
Revises: 0001_init_workspaces
Create Date: 2026-05-26 00:00:01.000000

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from fastapi_users_db_sqlalchemy.generics import GUID

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0002_add_users"
down_revision: str | None = "0001_init_workspaces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=1024), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "oauth_accounts",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("oauth_name", sa.String(length=100), nullable=False),
        sa.Column("access_token", sa.String(length=1024), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=True),
        sa.Column("refresh_token", sa.String(length=1024), nullable=True),
        sa.Column("account_id", sa.String(length=320), nullable=False),
        sa.Column("account_email", sa.String(length=320), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_oauth_accounts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_accounts")),
    )
    op.create_index(
        op.f("ix_oauth_accounts_account_id"),
        "oauth_accounts",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oauth_accounts_oauth_name"),
        "oauth_accounts",
        ["oauth_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_oauth_accounts_oauth_name"), table_name="oauth_accounts")
    op.drop_index(op.f("ix_oauth_accounts_account_id"), table_name="oauth_accounts")
    op.drop_table("oauth_accounts")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
