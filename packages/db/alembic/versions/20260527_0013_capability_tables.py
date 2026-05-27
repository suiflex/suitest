"""add LLM config, capability, MCP providers, generator/prompt/eval/code-export tables

Revision ID: 0013_capability_tables
Revises: 0012_audit_logs
Create Date: 2026-05-27 00:00:10.000000

Also resolves the DEFERRED FK from revision 0010:
``agent_sessions.prompt_version_id → prompt_versions.id`` is added here via
``op.create_foreign_key`` now that ``prompt_versions`` exists.

The ``tier`` enum was created in revision 0007 (runs) and is REUSED here for
``workspace_capabilities.tier`` (create_type=False, not created/dropped here).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0013_capability_tables"
down_revision: str | None = "0012_audit_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# tier reused from revision 0007 — referenced, never created/dropped here.
tier = postgresql.ENUM("ZERO", "LOCAL", "CLOUD", name="tier", create_type=False)
autonomy_level = postgresql.ENUM(
    "manual", "assist", "semi_auto", "auto", name="autonomy_level", create_type=False
)
mcp_transport = postgresql.ENUM("stdio", "sse", "ws", name="mcp_transport", create_type=False)

# enums OWNED by this migration (created + dropped here)
_OWNED_ENUMS = (autonomy_level, mcp_transport)

_AGENT_SESSIONS_PROMPT_FK = "fk_agent_sessions_prompt_version_id_prompt_versions"


def upgrade() -> None:
    bind = op.get_bind()
    for enum in _OWNED_ENUMS:
        enum.create(bind, checkfirst=True)

    # --- prompt_versions (created first so FKs below can reference it) ---
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_versions")),
        sa.UniqueConstraint("name", "version", name="uq_prompt_versions_name_version"),
    )
    op.create_index("ix_prompt_versions_hash", "prompt_versions", ["hash"], unique=False)

    # --- llm_configs ---
    op.create_table(
        "llm_configs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("api_key_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_llm_configs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_configs")),
    )
    op.create_index(
        "ix_llm_configs_workspace_active",
        "llm_configs",
        ["workspace_id", "is_active"],
        unique=False,
    )

    # --- workspace_capabilities (tier enum reused from 0007) ---
    op.create_table(
        "workspace_capabilities",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("tier", tier, nullable=False),
        sa.Column("autonomy_level", autonomy_level, nullable=False),
        sa.Column("features_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_capabilities_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_capabilities")),
        sa.UniqueConstraint("workspace_id", name=op.f("uq_workspace_capabilities_workspace_id")),
    )
    op.create_index(
        "ix_workspace_capabilities_tier", "workspace_capabilities", ["tier"], unique=False
    )

    # --- mcp_providers ---
    op.create_table(
        "mcp_providers",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("endpoint", sa.String(length=1024), nullable=False),
        sa.Column("transport", mcp_transport, nullable=False),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("secrets_json_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("is_default_for_target", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("health_status", sa.String(length=32), nullable=False),
        sa.Column("last_health_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_mcp_providers_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mcp_providers")),
        sa.UniqueConstraint("workspace_id", "name", name="uq_mcp_providers_workspace_name"),
    )
    op.create_index(
        "ix_mcp_providers_workspace_kind", "mcp_providers", ["workspace_id", "kind"], unique=False
    )

    # --- generator_runs ---
    op.create_table(
        "generator_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("input_meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_case_ids_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_generator_runs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_generator_runs_created_by_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generator_runs")),
    )
    op.create_index(
        "ix_generator_runs_workspace_source",
        "generator_runs",
        ["workspace_id", "source"],
        unique=False,
    )
    op.create_index("ix_generator_runs_created_at", "generator_runs", ["created_at"], unique=False)

    # --- eval_runs (FK to prompt_versions) ---
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("eval_suite_name", sa.String(length=120), nullable=False),
        sa.Column("fixtures_count", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.String(length=120), nullable=False),
        sa.Column("prompt_version_id", sa.String(length=32), nullable=True),
        sa.Column(
            "run_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("results_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_eval_runs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["prompt_versions.id"],
            name=op.f("fk_eval_runs_prompt_version_id_prompt_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_runs")),
    )
    op.create_index(
        "ix_eval_runs_workspace_suite",
        "eval_runs",
        ["workspace_id", "eval_suite_name"],
        unique=False,
    )

    # --- code_exports ---
    op.create_table(
        "code_exports",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("case_id", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("exported_code_text", sa.Text(), nullable=False),
        sa.Column(
            "exported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["test_cases.id"],
            name=op.f("fk_code_exports_case_id_test_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_code_exports_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_exports")),
    )
    op.create_index(
        "ix_code_exports_case_target", "code_exports", ["case_id", "target"], unique=False
    )

    # --- resolve deferred FK from revision 0010 ---
    op.create_foreign_key(
        _AGENT_SESSIONS_PROMPT_FK,
        "agent_sessions",
        "prompt_versions",
        ["prompt_version_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(_AGENT_SESSIONS_PROMPT_FK, "agent_sessions", type_="foreignkey")

    op.drop_index("ix_code_exports_case_target", table_name="code_exports")
    op.drop_table("code_exports")
    op.drop_index("ix_eval_runs_workspace_suite", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index("ix_generator_runs_created_at", table_name="generator_runs")
    op.drop_index("ix_generator_runs_workspace_source", table_name="generator_runs")
    op.drop_table("generator_runs")
    op.drop_index("ix_mcp_providers_workspace_kind", table_name="mcp_providers")
    op.drop_table("mcp_providers")
    op.drop_index("ix_workspace_capabilities_tier", table_name="workspace_capabilities")
    op.drop_table("workspace_capabilities")
    op.drop_index("ix_llm_configs_workspace_active", table_name="llm_configs")
    op.drop_table("llm_configs")
    op.drop_index("ix_prompt_versions_hash", table_name="prompt_versions")
    op.drop_table("prompt_versions")

    bind = op.get_bind()
    for enum in reversed(_OWNED_ENUMS):
        enum.drop(bind, checkfirst=True)
