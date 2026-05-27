"""AuditLog repository — append-only mutation log.

``before`` / ``after`` snapshots are folded into the model's ``metadata_json``
column (``{"before": ..., "after": ...}``) since the table has no dedicated
diff columns (docs/DATA_MODEL.md §3.11).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.audit import AuditLog
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime


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
