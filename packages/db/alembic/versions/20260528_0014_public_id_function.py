"""add generate_public_id function

Revision ID: 0014_public_id_function
Revises: 0013_capability_tables
Create Date: 2026-05-28 00:00:00.000000

Per-(workspace, prefix) sequence-backed public IDs. The plpgsql function
``generate_public_id(prefix TEXT, workspace_id TEXT)`` lazily creates a
``pubid_<workspace>_<prefix>`` sequence on first call (START 1000) and returns
``prefix || '-' || nextval`` — yielding e.g. ``TC-1000``, ``TC-1001`` for the
first two test cases of a workspace, ``TC-1000`` again for the same prefix in a
different workspace (separate sequence).

Function body verbatim from docs/DATA_MODEL.md §8. Per-entity ``before_insert``
event listeners (see ``suitest_db.public_id``) call this function from the
listener via ``conn.execute(text("SELECT generate_public_id(:p, :w)"))``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0014_public_id_function"
down_revision: str | None = "0013_capability_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Body per docs/DATA_MODEL.md §8. The ``quote_ident(seq_name)`` wrapping in the
# ``nextval`` call preserves case for uppercase prefixes (TC / REQ / SUIT) —
# without it Postgres folds the unquoted identifier to lowercase when resolving
# the regclass for ``nextval``, and the lookup misses the sequence created by
# ``CREATE SEQUENCE %I`` (which DOES preserve case). The visible behaviour
# matches §8: per-(workspace, prefix) sequence starting at 1000, returning
# ``prefix || '-' || nextval``.
_CREATE_FN = """
CREATE OR REPLACE FUNCTION generate_public_id(prefix TEXT, workspace_id TEXT)
RETURNS TEXT AS $$
DECLARE
  seq_name TEXT := 'pubid_' || replace(workspace_id, '-', '_') || '_' || prefix;
  next_val BIGINT;
BEGIN
  EXECUTE format('CREATE SEQUENCE IF NOT EXISTS %I START 1000', seq_name);
  EXECUTE format('SELECT nextval(%L)', quote_ident(seq_name)) INTO next_val;
  RETURN prefix || '-' || next_val;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(_CREATE_FN)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS generate_public_id(TEXT, TEXT)")
