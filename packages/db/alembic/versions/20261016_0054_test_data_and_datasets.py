"""Add workspace_variables, suite_variables, and test_cases datasets.

Revision ID: 0054_test_data_and_datasets
Revises: 0053_add_invitation_declined_at
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from suitest_db.types import PortableJSON

revision: str = "0054_test_data_and_datasets"
down_revision: str | None = "0053_add_invitation_declined_at"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 1. Create workspace_variables table
    op.create_table(
        "workspace_variables",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("is_secret", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("value_plain", sa.Text(), nullable=True),
        sa.Column("secret_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("workspace_id", "key", name="uq_workspace_variables_key"),
    )
    op.create_index(
        "ix_workspace_variables_workspace",
        "workspace_variables",
        ["workspace_id"],
    )

    # 2. Create suite_variables table
    op.create_table(
        "suite_variables",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "suite_id",
            sa.String(32),
            sa.ForeignKey("suites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("is_secret", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("value_plain", sa.Text(), nullable=True),
        sa.Column("secret_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("suite_id", "key", name="uq_suite_variables_key"),
    )
    op.create_index(
        "ix_suite_variables_suite",
        "suite_variables",
        ["suite_id"],
    )

    # 3. Add dataset_schema and dataset_rows to test_cases
    op.add_column(
        "test_cases",
        sa.Column("dataset_schema", PortableJSON, nullable=True),
    )
    op.add_column(
        "test_cases",
        sa.Column("dataset_rows", PortableJSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("test_cases", "dataset_rows")
    op.drop_column("test_cases", "dataset_schema")
    op.drop_index("ix_suite_variables_suite", table_name="suite_variables")
    op.drop_table("suite_variables")
    op.drop_index("ix_workspace_variables_workspace", table_name="workspace_variables")
    op.drop_table("workspace_variables")
