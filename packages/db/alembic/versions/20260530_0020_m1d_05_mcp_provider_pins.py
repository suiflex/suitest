"""m1d 05 mcp_providers.{command_pin, image_pin, version_pin, git_ref}

Revision ID: 0020_m1d_05_mcp_pins
Revises: 0019_m1d_04_gating_suite
Create Date: 2026-05-30 00:00:05.000000

Adds the four provenance / version pin columns required by ``MCP_PLUGINS §13``.
All nullable; the resolver populates whichever fits the active transport:

* ``stdio`` → ``command_pin`` (e.g. ``"jirac-mcp@jira-mcp-v2.0.1"``), plus
  optional ``git_ref`` for stdio-via-git transports (commit SHA or tag).
* docker / image → ``image_pin`` (e.g. ``"ghcr.io/suitest/postgres-mcp:0.7.1"``).
* SSE / WS → ``version_pin`` captured from the handshake
  ``serverInfo.version``.

Lengths mirror the ORM declaration in
``packages/db/src/suitest_db/models/mcp_provider.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0020_m1d_05_mcp_pins"
down_revision: str | None = "0019_m1d_04_gating_suite"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_providers",
        sa.Column("command_pin", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "mcp_providers",
        sa.Column("image_pin", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "mcp_providers",
        sa.Column("version_pin", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "mcp_providers",
        sa.Column("git_ref", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_providers", "git_ref")
    op.drop_column("mcp_providers", "version_pin")
    op.drop_column("mcp_providers", "image_pin")
    op.drop_column("mcp_providers", "command_pin")
