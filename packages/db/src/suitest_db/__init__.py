"""Suitest async DB layer."""

# Side-effect import: registers the global ``after_flush`` audit listener
# (``@event.listens_for(Session, ...)``) so every session emits AuditLog rows.
# NOT a barrel — nothing is re-exported (CLAUDE.md §2.2).
import suitest_db.audit  # noqa: F401

__version__ = "0.1.0"
