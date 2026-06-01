"""AgentSession repository (M3-5) — reproducibility-bearing session records.

Each session persists the exact ``model_id``, ``provider``, ``prompt_version_id``,
``seed`` and ``temperature`` used, plus rolled-up ``cost_usd`` / token counts on
completion. Messages + tool calls hang off the session for replay (docs/AI_AGENT.md
§13).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.agent import AgentMessage, AgentSession, AgentToolCall
from suitest_db.repositories.base import AsyncRepository
from suitest_shared.domain.enums import AgentSessionKind, MessageRole

if TYPE_CHECKING:
    from decimal import Decimal


class AgentSessionCreate(BaseModel):
    workspace_id: str
    kind: AgentSessionKind
    model_id: str
    provider: str
    user_id: uuid.UUID | None = None
    prompt_version_id: str | None = None
    seed: int | None = None
    temperature: float | None = None
    status: str = "active"
    metadata_json: dict[str, object] | None = None


class AgentSessionUpdate(BaseModel):
    status: str | None = None
    completed_at: datetime | None = None


class AgentSessionRepo(AsyncRepository[AgentSession, AgentSessionCreate, AgentSessionUpdate]):
    model = AgentSession

    async def complete(
        self,
        session_id: str,
        *,
        cost_usd: Decimal | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        status: str = "completed",
    ) -> AgentSession | None:
        """Finalize a session: stamp totals, status, and ``completed_at``."""
        row = await self.get_by_id(session_id)
        if row is None:
            return None
        row.status = status
        row.cost_usd = cost_usd
        row.tokens_in = tokens_in
        row.tokens_out = tokens_out
        row.completed_at = datetime.now(tz=UTC)
        await self.session.flush()
        return row

    async def add_message(
        self,
        session_id: str,
        *,
        role: MessageRole,
        content: str,
        metadata: dict[str, object] | None = None,
    ) -> AgentMessage:
        msg = AgentMessage(
            session_id=session_id, role=role, content=content, metadata_json=metadata
        )
        self.session.add(msg)
        await self.session.flush()
        return msg

    async def add_tool_call(
        self,
        message_id: str,
        *,
        tool_name: str,
        tool_input: dict[str, object],
        mcp_provider: str | None = None,
        output: dict[str, object] | None = None,
        status: str = "running",
        duration_ms: int | None = None,
        error_msg: str | None = None,
    ) -> AgentToolCall:
        call = AgentToolCall(
            message_id=message_id,
            tool_name=tool_name,
            mcp_provider=mcp_provider,
            input=tool_input,
            output=output,
            status=status,
            duration_ms=duration_ms,
            error_msg=error_msg,
        )
        self.session.add(call)
        await self.session.flush()
        return call

    async def list_messages(self, session_id: str) -> list[AgentMessage]:
        stmt = (
            select(AgentMessage)
            .where(AgentMessage.session_id == session_id)
            .order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc())
        )
        return list((await self.session.scalars(stmt)).all())
