"""add runs, run_steps, artifacts with tier_at_runtime

Revision ID: 0007_runs
Revises: 0006_requirements
Create Date: 2026-05-27 00:00:04.000000

The `tier` enum is FIRST created here (used by runs.tier_at_runtime). It is
reused later by `workspace_capabilities.tier` (Task 2k) — that migration
references it with create_type=False and does NOT recreate it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0007_runs"
down_revision: str | None = "0006_requirements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

run_status = postgresql.ENUM(
    "QUEUED",
    "RUNNING",
    "PASS",
    "FAIL",
    "CANCELLED",
    "ERROR",
    name="run_status",
    create_type=False,
)
run_trigger = postgresql.ENUM(
    "MANUAL",
    "SCHEDULED",
    "CI_PUSH",
    "CI_PR",
    "WEBHOOK",
    "AGENT",
    name="run_trigger",
    create_type=False,
)
step_outcome = postgresql.ENUM(
    "PASS", "FAIL", "SKIP", "ERROR", "PENDING", name="step_outcome", create_type=False
)
artifact_kind = postgresql.ENUM(
    "SCREENSHOT",
    "HAR",
    "DOM_SNAPSHOT",
    "VIDEO",
    "CONSOLE_LOG",
    "TRACE",
    "CUSTOM",
    name="artifact_kind",
    create_type=False,
)
tier = postgresql.ENUM("ZERO", "LOCAL", "CLOUD", name="tier", create_type=False)

_ENUMS = (run_status, run_trigger, step_outcome, artifact_kind, tier)


def upgrade() -> None:
    bind = op.get_bind()
    for enum in _ENUMS:
        enum.create(bind, checkfirst=True)

    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("public_id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("branch", sa.String(length=120), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("env", sa.String(length=32), nullable=False),
        sa.Column("trigger", run_trigger, nullable=False),
        sa.Column("triggered_by", sa.String(length=120), nullable=True),
        sa.Column("status", run_status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("tier_at_runtime", tier, nullable=False),
        sa.Column("total_steps", sa.Integer(), nullable=False),
        sa.Column("passed_steps", sa.Integer(), nullable=False),
        sa.Column("failed_steps", sa.Integer(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_runs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
        sa.UniqueConstraint("public_id", name=op.f("uq_runs_public_id")),
    )
    op.create_index("ix_runs_project_status", "runs", ["project_id", "status"], unique=False)
    op.create_index("ix_runs_created_at", "runs", ["created_at"], unique=False)
    op.create_index("ix_runs_tier", "runs", ["tier_at_runtime"], unique=False)

    op.create_table(
        "run_steps",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("case_id", sa.String(length=32), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("outcome", step_outcome, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=True),
        sa.Column("stderr", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_stack", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_run_steps_run_id_runs"), ondelete="CASCADE"
        ),
        # No CASCADE on case_id — preserve historical run data if a case is deleted.
        sa.ForeignKeyConstraint(
            ["case_id"], ["test_cases.id"], name=op.f("fk_run_steps_case_id_test_cases")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_steps")),
    )
    op.create_index("ix_run_steps_run_outcome", "run_steps", ["run_id", "outcome"], unique=False)

    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("run_step_id", sa.String(length=32), nullable=False),
        sa.Column("kind", artifact_kind, nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["run_step_id"],
            ["run_steps.id"],
            name=op.f("fk_artifacts_run_step_id_run_steps"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifacts")),
    )
    op.create_index("ix_artifacts_run_step_id", "artifacts", ["run_step_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_artifacts_run_step_id", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("ix_run_steps_run_outcome", table_name="run_steps")
    op.drop_table("run_steps")
    op.drop_index("ix_runs_tier", table_name="runs")
    op.drop_index("ix_runs_created_at", table_name="runs")
    op.drop_index("ix_runs_project_status", table_name="runs")
    op.drop_table("runs")

    bind = op.get_bind()
    for enum in reversed(_ENUMS):
        enum.drop(bind, checkfirst=True)
