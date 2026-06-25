"""UserBudget — per-user spend caps per workspace (M7-1).

``daily_cap_usd`` and ``monthly_cap_usd`` are Decimal(10,4) columns.
A value of 0 means "unlimited" (no cap enforced).

``(workspace_id, user_id)`` is UNIQUE — one budget row per user per workspace.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id


class UserBudget(Base, TimestampMixin):
    """Per-user daily/monthly LLM spend caps scoped to a workspace."""

    __tablename__ = "user_budgets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 0 = unlimited
    daily_cap_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, default=Decimal("0")
    )
    monthly_cap_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, default=Decimal("0")
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_user_budgets_workspace_user"),
        Index("ix_user_budgets_workspace_id", "workspace_id"),
    )
