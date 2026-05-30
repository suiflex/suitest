"""m1d 07 mcp_providers.workspace_id nullable + mcp_providers.enabled

Revision ID: 0022_m1d_07_mcp_ws_enabled
Revises: 0021_m1d_06_defect_dedup
Create Date: 2026-05-30 00:00:07.000000

Final structural change to ``mcp_providers`` before the bundled seed lands:

* Relax ``workspace_id`` to nullable so bundled / global providers (jirac-mcp,
  github-mcp, etc.) can be registered without forcing a sentinel workspace.
* Add ``enabled BOOLEAN NOT NULL DEFAULT 'true'`` so we can ship bundled
  providers in ``enabled=false`` state — they activate only on first
  integration connect (M1d-19).

Downgrade caveat (documented inline): rolling this back requires that the
seed migration (_08) has already been downgraded so no rows with
``workspace_id IS NULL`` remain — the linear chain handles this automatically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0022_m1d_07_mcp_ws_enabled"
down_revision: str | None = "0021_m1d_06_defect_dedup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "mcp_providers",
        "workspace_id",
        existing_type=sa.String(length=32),
        nullable=True,
    )
    op.add_column(
        "mcp_providers",
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("'true'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("mcp_providers", "enabled")
    op.alter_column(
        "mcp_providers",
        "workspace_id",
        existing_type=sa.String(length=32),
        nullable=False,
    )
