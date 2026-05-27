"""add users extension columns + memberships; extend workspaces with region

Revision ID: 0003_tenancy
Revises: 0002_add_users
Create Date: 2026-05-27 00:00:00.000000

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0003_tenancy"
down_revision: str | None = "0002_add_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

role_enum = postgresql.ENUM("OWNER", "ADMIN", "QA", "VIEWER", name="role", create_type=False)


def upgrade() -> None:
    # --- workspaces: additive region column ---
    # Add with a temporary server_default so the column is backfilled on populated
    # tables, then drop the default to match the ORM (Python-side default only).
    op.add_column(
        "workspaces",
        sa.Column(
            "region",
            sa.String(length=32),
            server_default="ap-southeast-1",
            nullable=False,
        ),
    )
    op.alter_column("workspaces", "region", server_default=None)

    # --- users: Suitest extension columns (additive on top of FastAPI-Users base) ---
    # `name` is NOT NULL in the target schema; add it with a temporary server_default
    # so the migration is safe on a populated table, then drop the default to match
    # the ORM (which declares no default).
    op.add_column(
        "users",
        sa.Column("name", sa.String(length=120), server_default="", nullable=False),
    )
    op.alter_column("users", "name", server_default=None)
    op.add_column("users", sa.Column("avatar_url", sa.String(length=500), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- memberships ---
    # First (and only) table using the `role` enum → create the PG type here.
    role_enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "memberships",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("role", role_enum, nullable=False),
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
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_memberships_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_memberships_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memberships")),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_memberships_workspace_user"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_table("memberships")
    role_enum.drop(op.get_bind(), checkfirst=True)

    op.drop_column("users", "updated_at")
    op.drop_column("users", "created_at")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "name")

    op.drop_column("workspaces", "region")
