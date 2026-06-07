"""PromptExperiment — A/B test between two prompt variants (M5-4).

Each experiment pits variant A against variant B for one prompt in one
workspace. A variant is either the file default (``*_override_id`` is NULL) or a
:class:`WorkspacePromptOverride` fork. ``split_pct`` is the target share of
impressions routed to B (0-100); the selector is deterministic and ratio-
preserving (no RNG, so runs stay reproducible). Per-variant impression / success
counters accumulate so the UI can show conversion and declare a winner.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from suitest_db.base import Base
from suitest_db.ids import new_id


class PromptExperiment(Base):
    __tablename__ = "prompt_experiments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    prompt_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="active", nullable=False
    )  # active|stopped
    # NULL → file default; otherwise a WorkspacePromptOverride fork.
    variant_a_override_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_prompt_overrides.id", ondelete="SET NULL")
    )
    variant_b_override_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_prompt_overrides.id", ondelete="SET NULL")
    )
    split_pct: Mapped[int] = mapped_column(Integer, default=50, nullable=False)  # % to B
    a_impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    a_successes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    b_impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    b_successes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_prompt_experiments_active", "workspace_id", "prompt_name", "status"),
    )
