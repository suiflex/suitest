"""test_cases: split display ``title`` from technical ``slug``.

``name`` historically carried whatever the publisher sent — for MCP/lifecycle
cases that is a snake_case function slug (``successful_login_opens_the_dashboard``),
which then leaked into the Cases and Runs UI. This migration introduces the
proper data model (docs/DATA_MODEL.md §3.4):

- ``title``  — human-readable display title, NOT NULL. Backfilled from ``name``:
  slug-shaped names are humanized to sentence case in SQL; already-human names
  copy verbatim.
- ``slug``   — technical key (automation function name, publish match key).
  Backfilled with ``name`` only when the name actually is slug-shaped.

``name`` stays as a backward-compatibility field (and publish idempotency key)
but is no longer a display field.

Revision ID: 0044_test_case_title_slug
Revises: 0043_api_key_encrypted
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0044_test_case_title_slug"
down_revision: str | None = "0043_api_key_encrypted"
branch_labels: str | None = None
depends_on: str | None = None

# Sentence-case humanization of a slug, in SQL: separators → spaces, squeeze
# whitespace, trim, upper-case the first character. (Acronym upper-casing is a
# nicety the app layer applies for NEW rows; the backfill keeps it simple.)
_HUMANIZED = (
    "upper(left(trim(regexp_replace(translate(name, '_-', '  '), '\\s+', ' ', 'g')), 1))"
    " || substr(trim(regexp_replace(translate(name, '_-', '  '), '\\s+', ' ', 'g')), 2)"
)


def upgrade() -> None:
    op.add_column("test_cases", sa.Column("title", sa.String(length=255), nullable=True))
    op.add_column("test_cases", sa.Column("slug", sa.String(length=255), nullable=True))

    # Slug-shaped name = contains '_' or '-', no whitespace.
    op.execute("UPDATE test_cases SET slug = name WHERE name !~ '\\s' AND name ~ '[_-]'")
    op.execute(
        f"UPDATE test_cases SET title = CASE WHEN slug IS NOT NULL THEN {_HUMANIZED} ELSE name END"
    )

    op.alter_column("test_cases", "title", nullable=False)
    op.create_index("ix_test_cases_suite_slug", "test_cases", ["suite_id", "slug"])


def downgrade() -> None:
    op.drop_index("ix_test_cases_suite_slug", table_name="test_cases")
    op.drop_column("test_cases", "slug")
    op.drop_column("test_cases", "title")
