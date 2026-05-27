"""Agent session / message / tool-call models (docs/DATA_MODEL.md §3.9).

Reproducibility fields (``provider``, ``prompt_version_id``, ``seed``,
``temperature``, ``cost_usd``) let a generation/diagnosis run be replayed.

``metadata`` is reserved on ``DeclarativeBase`` → Python attr ``metadata_json``,
DB column stays ``metadata``.

Deferred FK: the ``agent_sessions.prompt_version_id → prompt_versions.id``
constraint is added in the Task 2k migration (after ``prompt_versions`` exists).
The column's ``ForeignKey`` is added to this model in the same Task 2k change set
(when the ``prompt_version`` module is registered); declaring it earlier would make
SQLAlchemy mapper configuration fail with ``NoReferencedTableError`` because the
target table is not yet in the metadata.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from suitest_shared.domain.enums import AgentSessionKind, MessageRole

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id


class AgentSession(Base, TimestampMixin):
    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    kind: Mapped[AgentSessionKind] = mapped_column(
        SAEnum(AgentSessionKind, name="agent_session_kind"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)  # NEW
    # NEW — column now; FK constraint to prompt_versions added in Task 2k (both the
    # migration and the model's ForeignKey, once prompt_versions is registered).
    prompt_version_id: Mapped[str | None] = mapped_column(String(32))
    seed: Mapped[int | None] = mapped_column(Integer)  # NEW
    temperature: Mapped[float | None] = mapped_column(Float)  # NEW
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))  # NEW
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_agent_sessions_workspace_kind", "workspace_id", "kind"),
        Index("ix_agent_sessions_provider", "provider"),
    )


class AgentMessage(Base, TimestampMixin):
    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(
        SAEnum(MessageRole, name="message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

    __table_args__ = (Index("ix_agent_messages_session_id", "session_id"),)


class AgentToolCall(Base, TimestampMixin):
    __tablename__ = "agent_tool_calls"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("agent_messages.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    mcp_provider: Mapped[str | None] = mapped_column(String(64))  # NEW
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_msg: Mapped[str | None] = mapped_column(Text)
