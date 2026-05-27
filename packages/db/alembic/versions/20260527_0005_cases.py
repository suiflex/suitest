"""add test_cases, test_steps, case_tags with MCP routing fields

Revision ID: 0005_cases
Revises: 0004_projects_suites
Create Date: 2026-05-27 00:00:02.000000

Enum-creation pattern: every PG ENUM type is created explicitly via
``<enum>.create(bind, checkfirst=True)`` at the top of ``upgrade`` and then
referenced on columns with ``create_type=False``. This avoids the autogen
pitfall where the same type is emitted with ``create_type=True`` more than once
(which fails on upgrade).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0005_cases"
down_revision: str | None = "0004_projects_suites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

case_source = postgresql.ENUM(
    "MANUAL",
    "AI",
    "MCP",
    "IMPORT",
    "RECORDER",
    "HEURISTIC_CRAWL",
    name="case_source",
    create_type=False,
)
case_status = postgresql.ENUM(
    "DRAFT", "ACTIVE", "DEPRECATED", "ARCHIVED", name="case_status", create_type=False
)
priority = postgresql.ENUM("P0", "P1", "P2", "P3", name="priority", create_type=False)
target_kind = postgresql.ENUM(
    "BE_REST",
    "BE_GRAPHQL",
    "BE_GRPC",
    "FE_WEB",
    "FE_MOBILE",
    "DATA",
    "INFRA",
    "CUSTOM",
    name="target_kind",
    create_type=False,
)

_ENUMS = (case_source, case_status, priority, target_kind)


def upgrade() -> None:
    bind = op.get_bind()
    for enum in _ENUMS:
        enum.create(bind, checkfirst=True)

    op.create_table(
        "test_cases",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("suite_id", sa.String(length=32), nullable=False),
        sa.Column("public_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("preconditions", sa.Text(), nullable=True),
        sa.Column("source", case_source, nullable=False),
        sa.Column("status", case_status, nullable=False),
        sa.Column("priority", priority, nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("generated_by", sa.String(length=64), nullable=True),
        sa.Column("generated_from", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("estimated_ms", sa.Integer(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["suite_id"],
            ["suites.id"],
            name=op.f("fk_test_cases_suite_id_suites"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_test_cases_owner_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_cases")),
        sa.UniqueConstraint("public_id", name=op.f("uq_test_cases_public_id")),
    )
    op.create_index(
        "ix_test_cases_suite_status", "test_cases", ["suite_id", "status"], unique=False
    )
    op.create_index("ix_test_cases_source", "test_cases", ["source"], unique=False)
    op.create_index("ix_test_cases_deleted_at", "test_cases", ["deleted_at"], unique=False)

    op.create_table(
        "test_steps",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("case_id", sa.String(length=32), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("expected", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("mcp_provider", sa.String(length=64), nullable=False),
        sa.Column("target_kind", target_kind, nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["test_cases.id"],
            name=op.f("fk_test_steps_case_id_test_cases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_steps")),
        sa.UniqueConstraint("case_id", "order", name="uq_test_steps_case_order"),
    )
    op.create_index("ix_test_steps_mcp_provider", "test_steps", ["mcp_provider"], unique=False)
    op.create_index("ix_test_steps_target_kind", "test_steps", ["target_kind"], unique=False)

    op.create_table(
        "case_tags",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("case_id", sa.String(length=32), nullable=False),
        sa.Column("tag", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["test_cases.id"],
            name=op.f("fk_case_tags_case_id_test_cases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_tags")),
        sa.UniqueConstraint("case_id", "tag", name="uq_case_tags_case_tag"),
    )
    op.create_index("ix_case_tags_tag", "case_tags", ["tag"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_case_tags_tag", table_name="case_tags")
    op.drop_table("case_tags")
    op.drop_index("ix_test_steps_target_kind", table_name="test_steps")
    op.drop_index("ix_test_steps_mcp_provider", table_name="test_steps")
    op.drop_table("test_steps")
    op.drop_index("ix_test_cases_deleted_at", table_name="test_cases")
    op.drop_index("ix_test_cases_source", table_name="test_cases")
    op.drop_index("ix_test_cases_suite_status", table_name="test_cases")
    op.drop_table("test_cases")

    bind = op.get_bind()
    for enum in reversed(_ENUMS):
        enum.drop(bind, checkfirst=True)
