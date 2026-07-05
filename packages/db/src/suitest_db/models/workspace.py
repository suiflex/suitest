"""Workspace model — top-level tenant boundary (docs/DATA_MODEL.md §3.2)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id
from suitest_db.types import PortableJSON

if TYPE_CHECKING:
    # Runtime resolution happens via SQLAlchemy's class registry (string in
    # ``relationship("Membership", ...)``); importing at runtime here would create
    # a workspace ↔ tenancy import cycle.
    from suitest_db.models.tenancy import Membership  # noqa: TCH004


class Workspace(Base, TimestampMixin):
    """Workspace = top-level tenant boundary."""

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    region: Mapped[str] = mapped_column(String(32), default="ap-southeast-1", nullable=False)

    # M1d: toggles STEPS_REQUIRE_CODE_IN_ZERO_LLM per workspace (CAPABILITY_TIERS §6.3).
    strict_zero_validation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # M1d: workspace-scoped MCP routing override map per MCP_PLUGINS §4.1.
    # Shape: {"<target_kind>": "<mcp_provider_name>"}.
    mcp_routing_overrides: Mapped[dict[str, Any]] = mapped_column(
        PortableJSON, nullable=False, default=dict, server_default="'{}'"
    )

    # M1d-28: soft-delete tombstone for ``DELETE /workspaces/:id``. Reads
    # short-circuit when set so the FE hides the workspace immediately while
    # the async ``workspace_cleanup`` ARQ job tears down dependent rows.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list[Membership]] = relationship(
        "Membership", back_populates="workspace", cascade="all, delete-orphan"
    )
