"""RecorderSession — live browser-recorder session state (M2 Task 4).

One row per ``POST /generators/recorder/sessions``. Captured events stream in
over WebSocket and accumulate in ``captured_events_json``; ``finalize`` converts
them into a DRAFT :class:`~suitest_db.models.case.TestCase` and stamps
``finalized_case_id``. ``status`` advances ``active`` →
``finalized`` / ``cancelled`` / ``expired`` and is never written back to
``active``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from suitest_db.base import Base
from suitest_db.ids import new_id


class RecorderSession(Base):
    __tablename__ = "recorder_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    start_url: Mapped[str] = mapped_column(Text, nullable=False)
    mcp_provider: Mapped[str] = mapped_column(
        String(64), nullable=False, default="playwright-mcp", server_default="playwright-mcp"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    captured_events_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    ws_room: Mapped[str] = mapped_column(String(120), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_case_id: Mapped[str | None] = mapped_column(ForeignKey("test_cases.id"))

    __table_args__ = (Index("ix_recorder_sessions_workspace_status", "workspace_id", "status"),)
