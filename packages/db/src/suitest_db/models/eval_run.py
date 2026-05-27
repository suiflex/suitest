"""EvalRun — eval harness records, schema present in v1.0 (docs/DATA_MODEL.md §4.6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from suitest_db.base import Base
from suitest_db.ids import new_id


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    eval_suite_name: Mapped[str] = mapped_column(String(120), nullable=False)
    fixtures_count: Mapped[int] = mapped_column(Integer, nullable=False)
    passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    # FK to prompt_versions; created in the same Task 2k migration as prompt_versions.
    prompt_version_id: Mapped[str | None] = mapped_column(ForeignKey("prompt_versions.id"))
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    results_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (Index("ix_eval_runs_workspace_suite", "workspace_id", "eval_suite_name"),)
