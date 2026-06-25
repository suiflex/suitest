"""m9 plugin_registry — plugin_manifests table + seed data (M9-4)

Revision ID: 0036_m9_plugin_registry
Revises: 0035_m8_agent_plugins
Create Date: 2026-06-25 00:00:00.000000

Creates the ``plugin_manifests`` table for the marketplace concept page and
seeds four example manifests: XRay reporter, qTest reporter, Asana adapter,
and ClickUp adapter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0036_m9_plugin_registry"
down_revision: str | None = "0035_m8_agent_plugins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Seed IDs are deterministic so re-running upgrade on an empty DB is idempotent
# (ON CONFLICT DO NOTHING).
_SEEDS = [
    {
        "id": "pm0000000000000001",
        "name": "suitest-xray-reporter",
        "display_name": "XRay Test Reporter",
        "description": (
            "Submit Suitest run results to Xray (Jira Server or Xray Cloud) "
            "as test executions.  Requires an Xray token in config."
        ),
        "version": "1.0.0",
        "plugin_type": "reporter",
        "author": "Suitest Community",
        "homepage_url": "https://github.com/suiflex/suitest-xray-reporter",
        "install_command": "pip install suitest-xray-reporter",
        "is_official": False,
        "is_community": True,
    },
    {
        "id": "pm0000000000000002",
        "name": "suitest-qtest-reporter",
        "display_name": "qTest Reporter",
        "description": (
            "Push Suitest run results to qTest Manager as test runs.  "
            "Requires a qTest API token and project ID in config."
        ),
        "version": "1.0.0",
        "plugin_type": "reporter",
        "author": "Suitest Community",
        "homepage_url": "https://github.com/suiflex/suitest-qtest-reporter",
        "install_command": "pip install suitest-qtest-reporter",
        "is_official": False,
        "is_community": True,
    },
    {
        "id": "pm0000000000000003",
        "name": "suitest-asana-adapter",
        "display_name": "Asana Integration Adapter",
        "description": (
            "Create Asana tasks from Suitest defects and sync status back.  "
            "Requires an Asana personal access token and project GID in config."
        ),
        "version": "1.0.0",
        "plugin_type": "integration_adapter",
        "author": "Suitest Community",
        "homepage_url": "https://github.com/suiflex/suitest-asana-adapter",
        "install_command": "pip install suitest-asana-adapter",
        "is_official": False,
        "is_community": True,
    },
    {
        "id": "pm0000000000000004",
        "name": "suitest-clickup-adapter",
        "display_name": "ClickUp Integration Adapter",
        "description": (
            "Create ClickUp tasks from Suitest defects and sync status back.  "
            "Requires a ClickUp API token and list ID in config."
        ),
        "version": "1.0.0",
        "plugin_type": "integration_adapter",
        "author": "Suitest Community",
        "homepage_url": "https://github.com/suiflex/suitest-clickup-adapter",
        "install_command": "pip install suitest-clickup-adapter",
        "is_official": False,
        "is_community": True,
    },
]


def upgrade() -> None:
    op.create_table(
        "plugin_manifests",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column(
            "description",
            sa.String(length=2000),
            nullable=False,
            server_default="",
        ),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("plugin_type", sa.String(length=40), nullable=False),
        sa.Column("author", sa.String(length=200), nullable=True),
        sa.Column("homepage_url", sa.String(length=500), nullable=True),
        sa.Column("install_command", sa.String(length=500), nullable=True),
        sa.Column(
            "is_official",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "is_community",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_plugin_manifests_name"),
    )
    op.create_index(
        "ix_plugin_manifests_plugin_type",
        "plugin_manifests",
        ["plugin_type"],
    )

    # Seed example manifests (ON CONFLICT DO NOTHING for idempotency).
    plugin_manifests = sa.table(
        "plugin_manifests",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("display_name", sa.String),
        sa.column("description", sa.String),
        sa.column("version", sa.String),
        sa.column("plugin_type", sa.String),
        sa.column("author", sa.String),
        sa.column("homepage_url", sa.String),
        sa.column("install_command", sa.String),
        sa.column("is_official", sa.Boolean),
        sa.column("is_community", sa.Boolean),
    )
    op.bulk_insert(plugin_manifests, _SEEDS)


def downgrade() -> None:
    op.drop_index("ix_plugin_manifests_plugin_type", table_name="plugin_manifests")
    op.drop_table("plugin_manifests")
