"""WorkspacePromptOverride — DB-backed per-workspace prompt fork (M5-3).

A fork overrides a file-based default prompt (``prompts/{base_version}/{name}.md``,
see :mod:`suitest_agent.prompts.loader`) for ONE workspace. Forks are versioned:
each edit creates a new ``fork_version`` row so history is retained; exactly one
row per ``(workspace_id, prompt_name)`` is ``is_active`` and wins at resolution
time. The file default is always the fallback when no active fork exists, so the
ZERO/default path is unchanged.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from suitest_db.base import Base
from suitest_db.ids import new_id


class WorkspacePromptOverride(Base):
    __tablename__ = "workspace_prompt_overrides"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    prompt_name: Mapped[str] = mapped_column(
        String(120), nullable=False
    )  # e.g. "generate-from-prd"
    base_version: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # forked-from file version
    fork_version: Mapped[int] = mapped_column(Integer, nullable=False)  # per (workspace, prompt)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)  # sha256(content)
    label: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "prompt_name",
            "fork_version",
            name="uq_workspace_prompt_overrides_ws_name_ver",
        ),
        Index(
            "ix_workspace_prompt_overrides_active",
            "workspace_id",
            "prompt_name",
            "is_active",
        ),
    )
