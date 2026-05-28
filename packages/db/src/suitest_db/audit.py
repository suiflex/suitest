"""Audit log infrastructure — request context + SQLAlchemy mutation listener.

Every mutation flushed by SQLAlchemy against an :class:`~sqlalchemy.orm.Session`
emits an append-only ``AuditLog`` row capturing ``(workspace_id, user_id, action,
resource_type, resource_id, metadata=before/after diff, ip_address, user_agent)``.

The request-scoped attribution (who / from where) is carried out-of-band on a
``ContextVar`` so the listener stays a pure global hook with no DI plumbing. The
ASGI middleware (``suitest_api.middleware.audit``) sets it per request; background
jobs / Alembic migrations leave it unset and are therefore NOT audited.

Listener placement:
  We hook ``after_flush`` (not ``before_flush``) because INSERTed rows only have
  their server-resolved / default-generated primary keys after the flush. The
  ``AuditLog`` rows we add inside the handler are scheduled for the NEXT flush by
  SQLAlchemy. ``audit_logs`` is deliberately absent from :data:`AUDITED_TABLES`,
  so the audit insert does not re-trigger recording — no infinite recursion.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import get_history


@dataclass
class AuditContext:
    """Request-scoped attribution for audit rows. Any field may be ``None``."""

    user_id: str | None
    workspace_id: str | None
    ip_address: str | None
    user_agent: str | None


audit_ctx: ContextVar[AuditContext | None] = ContextVar("audit_ctx", default=None)


# Explicit allowlist of mutable domain tables. ``audit_logs`` is intentionally
# omitted so the listener never records its own writes (recursion guard).
AUDITED_TABLES: frozenset[str] = frozenset(
    {
        "test_cases",
        "test_steps",
        "case_tags",
        "runs",
        "run_steps",
        "artifacts",
        "defects",
        "external_issues",
        "requirements",
        "requirement_links",
        "integrations",
        "documents",
        "document_chunks",
        "llm_configs",
        "workspace_capabilities",
        "mcp_providers",
        "memberships",
        "projects",
        "suites",
    }
)


def _serialize_for_diff(value: object) -> object:
    """JSON-safe representation for a single audit diff value.

    ``metadata_json`` lands in a ``JSONB`` column via psycopg's default encoder,
    which can't handle ``datetime``/``date`` or arbitrary objects. We normalise
    here so the listener doesn't blow up the surrounding transaction the moment
    a tracked attribute happens to be a timestamp (most rows have at least one).
    StrEnum / IntEnum values flow through their ``.value`` so the JSON output is
    the wire-friendly string the rest of the API already uses.
    """
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return str(value)  # last-resort stringification for unexpected types


def _diff(target: object, mapper_attrs: list[str]) -> dict[str, list[object]]:
    """Return ``{attr: [old, new]}`` for every column attribute that changed.

    Uses :func:`sqlalchemy.orm.attributes.get_history`; an attribute counts as
    changed when its history reports a non-empty ``deleted`` (old) or ``added``
    (new) bucket. ``old``/``new`` are unwrapped from their single-element lists
    and passed through :func:`_serialize_for_diff` so the resulting dict serialises
    cleanly into the ``metadata_json`` ``JSONB`` column.
    """
    changes: dict[str, list[object]] = {}
    for attr in mapper_attrs:
        history = get_history(target, attr)
        if not history.has_changes():
            continue
        old = history.deleted[0] if history.deleted else None
        new = history.added[0] if history.added else None
        changes[attr] = [_serialize_for_diff(old), _serialize_for_diff(new)]
    return changes


def _column_attrs(target: object) -> list[str]:
    """Mapped column attribute keys for ``target`` (relationships excluded)."""
    mapper = getattr(type(target), "__mapper__", None)
    if mapper is None:
        return []
    return [col.key for col in mapper.column_attrs]


def _record(session: Session, target: object, action: str) -> None:
    """Add one ``AuditLog`` row for ``target`` unless it should be skipped.

    Skips when there is no request context (background / migration writes) or no
    workspace bound, and when the target table is not in :data:`AUDITED_TABLES`.
    """
    ctx = audit_ctx.get()
    if ctx is None or ctx.workspace_id is None:
        return  # background tasks / migrations skip
    tablename = getattr(target, "__tablename__", None)
    if tablename not in AUDITED_TABLES:
        return

    from suitest_db.models.audit import AuditLog  # late import to avoid cycle

    resource_id = getattr(target, "public_id", None) or getattr(target, "id", None)
    meta: dict[str, dict[str, list[object]]] | None = (
        {"changes": _diff(target, _column_attrs(target))} if action == "update" else None
    )
    row = AuditLog(
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        action=action,
        resource_type=tablename,
        resource_id=str(resource_id),
        metadata_json=meta,
        ip_address=ctx.ip_address,
        user_agent=ctx.user_agent,
    )
    session.add(row)


@event.listens_for(Session, "after_flush")
def _after_flush(session: Session, flush_context: object) -> None:
    """Record insert/update/delete for every mutated object in the flush."""
    for obj in session.new:
        _record(session, obj, "insert")
    for obj in session.dirty:
        if session.is_modified(obj, include_collections=False):
            _record(session, obj, "update")
    for obj in session.deleted:
        _record(session, obj, "delete")
