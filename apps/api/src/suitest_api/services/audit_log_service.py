"""AuditLogService — workspace-scoped read of the append-only audit trail.

Service responsibility (M1d-27 — docs/API.md §146-158):

* Translate the public ``action`` glob (``integration.*``, ``case.deleted``,
  ``*``) into a SQL ``LIKE`` pattern (``%`` / ``_`` literals in user input
  escaped first; ``*`` → ``%``, ``?`` → ``_``).
* Coerce the ``user_id`` string into ``uuid.UUID`` (returning ``None`` on a
  malformed cast so the caller can decide between 400 and silently empty).
* Hand the assembled criteria to :class:`AuditLogRepo` for the keyset query.
* Map the joined ``(AuditLog, user_email)`` rows into :class:`AuditLogRead`.

Role + tenant gating happen in the router (``require_role({ADMIN, OWNER})`` +
``require_workspace_membership``). The service trusts ``ctx.workspace_id`` and
only ever issues queries scoped to it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from suitest_db.repositories.audit_logs import AuditLogRepo

from suitest_api.schemas.audit_log import AuditLogRead

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from suitest_api.deps.scope import TenantContext


# SQL ``LIKE`` metacharacters that must be escaped before glob translation so a
# caller cannot inject an unintended wildcard via the public ``action`` filter.
# ``\`` is escaped first so the subsequent ``%`` / ``_`` escapes do not double
# escape themselves.
_LIKE_ESCAPE_CHARS: tuple[str, ...] = ("\\", "%", "_")


def glob_to_like(pattern: str) -> str:
    """Translate a public glob (``integration.*``, ``case_?``) into a SQL LIKE.

    Order of operations matters: literal SQL ``%`` / ``_`` in the user input
    are escaped first (so ``50%_off`` matches the literal substring) and only
    then are ``*`` / ``?`` mapped to ``%`` / ``_``. The Postgres default LIKE
    escape character (``\\``) is the same as ours, so the predicate at the
    repo layer is ``column LIKE :pattern ESCAPE '\\'``.
    """
    escaped = pattern
    for ch in _LIKE_ESCAPE_CHARS:
        escaped = escaped.replace(ch, "\\" + ch)
    # Now translate the glob wildcards. ``*`` -> ``%``, ``?`` -> ``_``.
    return escaped.replace("*", "%").replace("?", "_")


@dataclass(frozen=True)
class AuditLogPage:
    """Service-shape page returned to the router (already DTO-mapped)."""

    items: list[AuditLogRead]
    next_cursor: tuple[datetime, str] | None


class AuditLogService:
    """Read the workspace audit trail with cursor pagination + glob filter."""

    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    async def list_page(
        self,
        *,
        cursor: tuple[datetime, str] | None,
        action: str | None,
        resource_type: str | None,
        user_id: uuid.UUID | None,
        from_ts: datetime | None,
        to_ts: datetime | None,
        limit: int,
    ) -> AuditLogPage:
        """Fetch one keyset-paginated page of audit rows scoped to the workspace."""
        action_pattern = glob_to_like(action) if action is not None else None
        repo = AuditLogRepo(self._session)
        rows, next_cursor = await repo.list_paginated_filtered(
            workspace_id=self._ctx.workspace_id,
            cursor=cursor,
            action_pattern=action_pattern,
            resource_type=resource_type,
            user_id=user_id,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit,
        )
        items = [
            AuditLogRead(
                id=row[0].id,
                workspace_id=row[0].workspace_id,
                user_id=str(row[0].user_id) if row[0].user_id is not None else None,
                user_email=row[1],
                action=row[0].action,
                resource_type=row[0].resource_type,
                resource_id=row[0].resource_id,
                details=row[0].metadata_json,
                created_at=row[0].created_at,
            )
            for row in rows
        ]
        return AuditLogPage(items=items, next_cursor=next_cursor)
