"""AuditLog repository — append-only mutation log.

``before`` / ``after`` snapshots are folded into the model's ``metadata_json``
column (``{"before": ..., "after": ...}``) since the table has no dedicated
diff columns (docs/DATA_MODEL.md §3.11).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import Row, select
from suitest_db.models.audit import AuditLog
from suitest_db.models.user import User
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.orm import InstrumentedAttribute


class AuditLogCreate(BaseModel):
    workspace_id: str
    action: str
    resource_type: str
    resource_id: str
    user_id: uuid.UUID | None = None
    metadata_json: dict[str, object] | None = None
    ip_address: str | None = None
    user_agent: str | None = None


class AuditLogUpdate(BaseModel):
    """Audit rows are immutable — no updatable fields."""


class AuditLogRepo(AsyncRepository[AuditLog, AuditLogCreate, AuditLogUpdate]):
    model = AuditLog

    async def list_by_workspace(
        self,
        workspace_id: str,
        *,
        cursor: tuple[datetime, str] | None = None,
        limit: int = 20,
    ) -> tuple[Sequence[AuditLog], tuple[datetime, str] | None]:
        stmt = select(AuditLog).where(AuditLog.workspace_id == workspace_id)
        if cursor is not None:
            cursor_ts, cursor_id = cursor
            stmt = stmt.where(
                (AuditLog.created_at < cursor_ts)
                | ((AuditLog.created_at == cursor_ts) & (AuditLog.id < cursor_id))
            )
        stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit + 1)

        rows = list((await self.session.scalars(stmt)).all())
        if len(rows) > limit:
            page = rows[:limit]
            last = page[-1]
            next_cursor: tuple[datetime, str] | None = (last.created_at, last.id)
        else:
            page = rows
            next_cursor = None
        return page, next_cursor

    async def list_paginated_filtered(
        self,
        *,
        workspace_id: str,
        cursor: tuple[datetime, str] | None = None,
        action_pattern: str | None = None,
        resource_type: str | None = None,
        user_id: uuid.UUID | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        limit: int = 50,
    ) -> tuple[Sequence[Row[tuple[AuditLog, str | None]]], tuple[datetime, str] | None]:
        """Cursor-paginated workspace audit list with full M1d-27 filter set.

        ``action_pattern`` is a pre-translated SQL ``LIKE`` pattern (caller
        converts ``integration.*`` glob → ``integration.%``). ``from_ts`` and
        ``to_ts`` are inclusive datetime bounds. Joins ``users`` to surface the
        actor email; returns ``Row[(AuditLog, email_or_None)]`` pairs so the
        caller does not need a second round-trip.
        """
        # ``User`` inherits ``email`` from FastAPI-Users' base which types the
        # attribute as a plain ``str`` for the ORM mixin — at runtime SQLAlchemy
        # rebinds it as an ``InstrumentedAttribute``. The cast keeps mypy happy
        # without ``# type: ignore`` litter on every column reference.
        # The outer join makes the email column nullable in the result row.
        user_email_col: InstrumentedAttribute[str | None] = User.__table__.c.email  # type: ignore[assignment]
        user_id_col: InstrumentedAttribute[uuid.UUID] = User.__table__.c.id  # type: ignore[assignment]
        stmt = (
            select(AuditLog, user_email_col)
            .outerjoin(User, AuditLog.user_id == user_id_col)
            .where(AuditLog.workspace_id == workspace_id)
        )
        if cursor is not None:
            cursor_ts, cursor_id = cursor
            stmt = stmt.where(
                (AuditLog.created_at < cursor_ts)
                | ((AuditLog.created_at == cursor_ts) & (AuditLog.id < cursor_id))
            )
        if action_pattern is not None:
            # Pattern already includes SQL wildcards (% / _). Escape the literal
            # backslash to keep ``\%`` / ``\_`` working as escapes (Postgres default).
            stmt = stmt.where(AuditLog.action.like(action_pattern, escape="\\"))
        if resource_type is not None:
            stmt = stmt.where(AuditLog.resource_type == resource_type)
        if user_id is not None:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if from_ts is not None:
            stmt = stmt.where(AuditLog.created_at >= from_ts)
        if to_ts is not None:
            stmt = stmt.where(AuditLog.created_at <= to_ts)

        stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit + 1)

        rows = list((await self.session.execute(stmt)).all())
        if len(rows) > limit:
            page = rows[:limit]
            last_audit: AuditLog = page[-1][0]
            next_cursor: tuple[datetime, str] | None = (last_audit.created_at, last_audit.id)
        else:
            page = rows
            next_cursor = None
        return page, next_cursor

    async def list_by_workspace_filtered(
        self,
        *,
        workspace_id: str,
        action_prefix: str | None = None,
        limit: int = 20,
    ) -> Sequence[AuditLog]:
        """List audit rows for a workspace, optionally filtered by ``action`` prefix.

        Used by the Dashboard agent activity feed (``GET /audit-logs?action=agent.*``).
        Trailing ``.*`` / ``*`` wildcards are stripped before the ``LIKE`` lookup so
        callers can pass the canonical glob form. Ordered newest-first; no cursor —
        this is a small bounded read (limit ≤ 100), pagination lands when needed.
        """
        stmt = select(AuditLog).where(AuditLog.workspace_id == workspace_id)
        if action_prefix:
            normalized = action_prefix.rstrip("*").rstrip(".")
            if normalized:
                stmt = stmt.where(AuditLog.action.like(f"{normalized}%"))
        stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
        return (await self.session.scalars(stmt)).all()

    async def append(
        self,
        *,
        workspace_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        before: dict[str, object] | None = None,
        after: dict[str, object] | None = None,
        user_id: uuid.UUID | None = None,
        ip: str | None = None,
        ua: str | None = None,
    ) -> AuditLog:
        metadata: dict[str, object] | None = None
        if before is not None or after is not None:
            metadata = {"before": before, "after": after}
        row = AuditLog(
            workspace_id=workspace_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            metadata_json=metadata,
            ip_address=ip,
            user_agent=ua,
        )
        self.session.add(row)
        await self.session.flush()
        return row
