"""Suitest async DB layer."""

# Side-effect import: registers the global ``after_flush`` audit listener
# (``@event.listens_for(Session, ...)``) so every session emits AuditLog rows.
# NOT a barrel — nothing is re-exported (CLAUDE.md §2.2).
import suitest_db.audit

# Side-effect import: registers per-model ``before_insert`` listeners that fill
# ``public_id`` via the Postgres ``generate_public_id`` function. See
# ``suitest_db/public_id.py`` for details. NOT a barrel.
import suitest_db.public_id  # noqa: F401

__version__ = "0.1.0"
