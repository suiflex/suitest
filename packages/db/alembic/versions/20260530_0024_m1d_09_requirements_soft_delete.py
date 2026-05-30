"""m1d 09 requirements.deleted_at + partial active index

Revision ID: 0024_m1d_09_req_soft_delete
Revises: 0023_m1d_08_seed_bundled_mcp
Create Date: 2026-05-30 00:00:09.000000

Requirement-level changes required by M1d-6 (Requirement + Link CRUD):

* ``requirements.deleted_at`` — soft-delete tombstone set by
  ``DELETE /requirements/:id`` and cleared by ``POST /requirements/:id/restore``.
  List / GET endpoints filter ``deleted_at IS NULL`` by default; tombstones
  remain in the DB so audit + restore work.
* Partial index ``ix_requirements_project_active`` — covers the default
  active-list query (``WHERE project_id = ? AND deleted_at IS NULL``). Hard
  purge sweeper deferred to M2+.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0024_m1d_09_req_soft_delete"
down_revision: str | None = "0023_m1d_08_seed_bundled_mcp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "requirements",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_requirements_project_active",
        "requirements",
        ["project_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_requirements_deleted_at",
        "requirements",
        ["deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_requirements_deleted_at", table_name="requirements")
    op.drop_index("ix_requirements_project_active", table_name="requirements")
    op.drop_column("requirements", "deleted_at")
