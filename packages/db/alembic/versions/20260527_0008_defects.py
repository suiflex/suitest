"""add defects + external issues with diagnosis_kind

Revision ID: 0008_defects
Revises: 0007_runs
Create Date: 2026-05-27 00:00:05.000000

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0008_defects"
down_revision: str | None = "0007_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

severity = postgresql.ENUM("CRITICAL", "HIGH", "MEDIUM", "LOW", name="severity", create_type=False)
defect_status = postgresql.ENUM(
    "OPEN",
    "IN_PROGRESS",
    "RESOLVED",
    "CLOSED",
    "WONT_FIX",
    name="defect_status",
    create_type=False,
)
diagnosis_kind = postgresql.ENUM(
    "REGRESSION",
    "FLAKE",
    "INFRA",
    "SPEC_DRIFT",
    "MANUAL_TRIAGE",
    name="diagnosis_kind",
    create_type=False,
)

_ENUMS = (severity, defect_status, diagnosis_kind)


def upgrade() -> None:
    bind = op.get_bind()
    for enum in _ENUMS:
        enum.create(bind, checkfirst=True)

    op.create_table(
        "defects",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("public_id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("test_case_id", sa.String(length=32), nullable=True),
        sa.Column("run_id", sa.String(length=32), nullable=True),
        sa.Column("requirement_id", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("severity", severity, nullable=False),
        sa.Column("status", defect_status, nullable=False),
        sa.Column("component", sa.String(length=120), nullable=True),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_diagnosis", sa.Text(), nullable=True),
        sa.Column("agent_diagnosis_kind", diagnosis_kind, nullable=False),
        sa.Column("agent_confidence", sa.Float(), nullable=True),
        sa.Column("stack_trace", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_defects_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id"], ["test_cases.id"], name=op.f("fk_defects_test_case_id_test_cases")
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_defects_run_id_runs")),
        sa.ForeignKeyConstraint(
            ["requirement_id"],
            ["requirements.id"],
            name=op.f("fk_defects_requirement_id_requirements"),
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"], ["users.id"], name=op.f("fk_defects_assignee_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_defects")),
        sa.UniqueConstraint("public_id", name=op.f("uq_defects_public_id")),
    )
    op.create_index(
        "ix_defects_workspace_status", "defects", ["workspace_id", "status"], unique=False
    )
    op.create_index("ix_defects_severity", "defects", ["severity"], unique=False)
    op.create_index("ix_defects_diagnosis_kind", "defects", ["agent_diagnosis_kind"], unique=False)

    op.create_table(
        "external_issues",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("defect_id", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("external_url", sa.String(length=1024), nullable=False),
        sa.Column(
            "synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["defect_id"],
            ["defects.id"],
            name=op.f("fk_external_issues_defect_id_defects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_issues")),
        sa.UniqueConstraint("provider", "external_id", name="uq_external_issues_provider_external"),
    )


def downgrade() -> None:
    op.drop_table("external_issues")
    op.drop_index("ix_defects_diagnosis_kind", table_name="defects")
    op.drop_index("ix_defects_severity", table_name="defects")
    op.drop_index("ix_defects_workspace_status", table_name="defects")
    op.drop_table("defects")

    bind = op.get_bind()
    for enum in reversed(_ENUMS):
        enum.drop(bind, checkfirst=True)
