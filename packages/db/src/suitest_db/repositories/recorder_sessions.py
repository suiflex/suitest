"""RecorderSession repository — live browser-recorder session state (M2 Task 4).

Workspace-scoped lookups return ``None`` for cross-workspace ids so the API
layer answers 404 (never 403) and a caller cannot probe sessions in other
tenants. ``append_event`` reassigns the whole ``captured_events_json`` list
(rather than mutating in place) so SQLAlchemy's change tracking flags the JSONB
column dirty and flushes it.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.recorder_session import RecorderSession
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class RecorderSessionCreate(BaseModel):
    workspace_id: str
    user_id: str | None = None
    project_id: str
    start_url: str
    mcp_provider: str = "playwright-mcp"
    ws_room: str
    expires_at: datetime
    status: str = "active"
    captured_events_json: list[dict[str, Any]] = []


class RecorderSessionUpdate(BaseModel):
    status: str | None = None
    finalized_at: datetime | None = None
    finalized_case_id: str | None = None


class RecorderSessionRepo(
    AsyncRepository[RecorderSession, RecorderSessionCreate, RecorderSessionUpdate]
):
    model = RecorderSession

    async def get_by_id(
        self, id: str, *, workspace_id: str | None = None
    ) -> RecorderSession | None:
        """Load one session by id, optionally constrained to ``workspace_id``.

        When ``workspace_id`` is supplied a row owned by a different workspace
        resolves to ``None`` (the caller maps this to 404) so cross-tenant ids
        are indistinguishable from missing ones.
        """
        stmt = select(RecorderSession).where(RecorderSession.id == id)
        if workspace_id is not None:
            stmt = stmt.where(RecorderSession.workspace_id == workspace_id)
        result: RecorderSession | None = await self.session.scalar(stmt)
        return result

    async def update_status(
        self, id: str, status: str, *, workspace_id: str | None = None
    ) -> RecorderSession | None:
        """Set ``status`` on an (optionally workspace-scoped) session."""
        row = await self.get_by_id(id, workspace_id=workspace_id)
        if row is None:
            return None
        row.status = status
        await self.session.flush()
        return row

    async def append_event(
        self, id: str, event: dict[str, Any], *, workspace_id: str | None = None
    ) -> RecorderSession | None:
        """Append one captured event to ``captured_events_json``.

        Reassigns the list so the JSONB column is marked dirty (in-place
        ``.append`` would not be tracked).
        """
        row = await self.get_by_id(id, workspace_id=workspace_id)
        if row is None:
            return None
        row.captured_events_json = [*row.captured_events_json, event]
        await self.session.flush()
        return row

    async def mark_finalized(
        self,
        id: str,
        *,
        finalized_case_id: str,
        finalized_at: datetime,
        workspace_id: str | None = None,
    ) -> RecorderSession | None:
        """Transition a session to ``finalized`` + stamp the produced case id."""
        row = await self.get_by_id(id, workspace_id=workspace_id)
        if row is None:
            return None
        row.status = "finalized"
        row.finalized_case_id = finalized_case_id
        row.finalized_at = finalized_at
        await self.session.flush()
        return row

    async def list_active_expired(self, now: datetime) -> Sequence[RecorderSession]:
        """Return every still-``active`` session whose TTL has elapsed."""
        stmt = select(RecorderSession).where(
            RecorderSession.status == "active",
            RecorderSession.expires_at < now,
        )
        return (await self.session.scalars(stmt)).all()
