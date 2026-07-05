"""GeneratorRun — deterministic generator traceability (docs/DATA_MODEL.md §4.4)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from suitest_db.base import Base
from suitest_db.ids import new_id
from suitest_db.types import PortableJSON


class GeneratorRun(Base):
    __tablename__ = "generator_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    # openapi | recorder | heuristic_crawl | prd | url_semantic | mcp_discovery
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    input_meta_json: Mapped[dict[str, object]] = mapped_column(
        PortableJSON, default=dict, nullable=False
    )
    output_case_ids_json: Mapped[list[str]] = mapped_column(
        PortableJSON, default=list, nullable=False
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    __table_args__ = (
        Index("ix_generator_runs_workspace_source", "workspace_id", "source"),
        Index("ix_generator_runs_created_at", "created_at"),
    )
