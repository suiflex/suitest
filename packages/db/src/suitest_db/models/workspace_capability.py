"""WorkspaceCapability — materialized tier + autonomy snapshot (docs/DATA_MODEL.md §4.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from suitest_shared.domain.enums import AutonomyLevel, Tier

from suitest_db.base import Base
from suitest_db.ids import new_id
from suitest_db.types import PortableJSON


class WorkspaceCapability(Base):
    __tablename__ = "workspace_capabilities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    tier: Mapped[Tier] = mapped_column(SAEnum(Tier, name="tier"), nullable=False)
    autonomy_level: Mapped[AutonomyLevel] = mapped_column(
        SAEnum(
            AutonomyLevel,
            name="autonomy_level",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=AutonomyLevel.MANUAL,
        nullable=False,
    )
    features_json: Mapped[dict[str, Any]] = mapped_column(
        PortableJSON, default=dict, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_workspace_capabilities_tier", "tier"),)
