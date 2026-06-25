"""AgentDefinition ORM model — workspace-scoped custom agent plugin definitions (M8).

A row stores the raw YAML spec for a workspace-registered agent plugin.
The parsed ``spec_version`` is denormalised for fast ordering/filtering.
Soft-delete via ``is_active``; unique constraint prevents duplicate active names
per workspace.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id


class AgentDefinition(Base, TimestampMixin):
    """Workspace-scoped custom agent plugin definition."""

    __tablename__ = "agent_definitions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    spec_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    spec_version: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # TimestampMixin provides created_at / updated_at

    __table_args__ = (
        # Partial unique index: only one active definition per (workspace, name).
        # Enforced as a DDL-only Index with postgresql_where so deactivated rows
        # (is_active=False) don't block re-registration of the same name.
        Index(
            "uq_agent_definitions_workspace_active_name",
            "workspace_id",
            "name",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
        Index("ix_agent_definitions_workspace_id", "workspace_id"),
        Index("ix_agent_definitions_name", "name"),
    )
