"""m1d 08 seed bundled jirac-mcp + github-mcp rows (workspace_id NULL, enabled=false)

Revision ID: 0023_m1d_08_seed_bundled_mcp
Revises: 0022_m1d_07_mcp_ws_enabled
Create Date: 2026-05-30 00:00:08.000000

Ships the two bundled MCP integration-tracker providers M1d-12 / M1d-14 will
wrap. Both rows are ``workspace_id IS NULL`` (global / bundled) and
``enabled=false`` until a workspace connects the integration for the first
time (M1d-19 flips the flag via
``McpProviderRepository.flip_enabled``).

The ``command_pin`` values are pinned to the bundled binary versions per
plan-05b § M1d-12 / M1d-14 acceptance criteria — when those tasks land the
Dockerfile + adapter must match these pins exactly.

Stable bundled IDs are used (``mcp_builtin_jirac`` / ``mcp_builtin_github``)
so subsequent migrations and tests can reference them without re-querying
by name. ``new_id``-style randoms would make integration tests flakier.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0023_m1d_08_seed_bundled_mcp"
down_revision: str | None = "0022_m1d_07_mcp_ws_enabled"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BUNDLED_NAMES = ("jirac-mcp", "github-mcp")

# Stable bundled IDs (must stay <= 32 chars to fit String(32)).
_JIRAC_ID = "mcp_builtin_jirac_0000000000000"  # 32 chars
_GITHUB_ID = "mcp_builtin_github_000000000000"  # 32 chars


def upgrade() -> None:
    # Snapshot table matching the post-_07 schema. We do NOT reference
    # ``Base.metadata`` here so this migration stays runnable even if the ORM
    # diverges later.
    mcp_providers = sa.table(
        "mcp_providers",
        sa.column("id", sa.String(length=32)),
        sa.column("workspace_id", sa.String(length=32)),
        sa.column("name", sa.String(length=120)),
        sa.column("kind", sa.String(length=64)),
        sa.column("endpoint", sa.String(length=1024)),
        sa.column(
            "transport",
            postgresql.ENUM("stdio", "sse", "ws", name="mcp_transport", create_type=False),
        ),
        sa.column("config_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("is_default_for_target", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("health_status", sa.String(length=32)),
        sa.column("command_pin", sa.String(length=200)),
        sa.column("enabled", sa.Boolean()),
    )

    op.bulk_insert(
        mcp_providers,
        [
            {
                "id": _JIRAC_ID,
                "workspace_id": None,
                "name": "jirac-mcp",
                "kind": "issue-tracker",
                "endpoint": "jirac-mcp serve --transport stdio",
                "transport": "stdio",
                "config_json": {},
                "is_default_for_target": {},
                "health_status": "unknown",
                "command_pin": "jirac-mcp@jira-mcp-v2.0.1",
                "enabled": False,
            },
            {
                "id": _GITHUB_ID,
                "workspace_id": None,
                "name": "github-mcp",
                "kind": "issue-tracker",
                "endpoint": "github-mcp-server stdio --toolsets issues",
                "transport": "stdio",
                "config_json": {},
                "is_default_for_target": {},
                "health_status": "unknown",
                "command_pin": "github-mcp-server@v1.1.2",
                "enabled": False,
            },
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM mcp_providers WHERE workspace_id IS NULL AND name IN :names"
        ).bindparams(sa.bindparam("names", _BUNDLED_NAMES, expanding=True))
    )
