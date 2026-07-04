"""test_cases: STALE status + (suite_id, slug) uniqueness guard.

Retest hardening (MCP lifecycle):

- ``case_status`` enum gains ``STALE`` — a previously-published MCP case that
  the latest generation no longer produced (its scenario disappeared from the
  app). Distinct from DEPRECATED (human decision) and ARCHIVED (hidden).
- Partial unique index ``uq_test_cases_suite_slug`` on (suite_id, slug) for
  active rows with a slug. Bulk-import already dedupes application-side; the
  index makes duplicate TestCases from concurrent retests impossible at the DB
  layer. Pre-existing duplicates are disambiguated first (older rows get a
  ``-dup-<id>`` slug suffix so history is kept, the newest row keeps the key).

Revision ID: 0046_case_stale_slug_guard
Revises: 0045_drop_chunk_embedding
Create Date: 2026-07-05
"""

from __future__ import annotations

from alembic import op

revision: str = "0046_case_stale_slug_guard"
down_revision: str | None = "0045_drop_chunk_embedding"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # PG12+ allows ADD VALUE inside a transaction as long as the new value is
    # not used in the same transaction — this migration never writes STALE.
    op.execute("ALTER TYPE case_status ADD VALUE IF NOT EXISTS 'STALE'")

    # Disambiguate pre-existing duplicates: keep the most recently updated row
    # per (suite_id, slug), suffix the rest so no data is lost.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY suite_id, slug
                       ORDER BY updated_at DESC, id DESC
                   ) AS rn
            FROM test_cases
            WHERE slug IS NOT NULL AND deleted_at IS NULL
        )
        UPDATE test_cases t
        SET slug = t.slug || '-dup-' || t.id
        FROM ranked r
        WHERE t.id = r.id AND r.rn > 1
        """
    )
    op.create_index(
        "uq_test_cases_suite_slug",
        "test_cases",
        ["suite_id", "slug"],
        unique=True,
        postgresql_where="slug IS NOT NULL AND deleted_at IS NULL",
    )


def downgrade() -> None:
    op.drop_index("uq_test_cases_suite_slug", table_name="test_cases")
    # PG cannot drop an enum value in place; leaving STALE in the type is
    # harmless for older code (it just never writes it).
