"""Project + Suite models (docs/DATA_MODEL.md §3.3)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id
from suitest_db.types import PortableJSON

if TYPE_CHECKING:
    # Resolved at runtime via SQLAlchemy's registry; a runtime import would create
    # a workspace ↔ project cycle.
    from suitest_db.models.workspace import Workspace  # noqa: TCH004


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2048))
    # M1d: optional pinned smoke suite used as gating target for webhook-triggered
    # runs (M1d-16) and the autopilot "promote to gating" action (M1d-26).
    # FK ON DELETE SET NULL — deleting the suite nulls the pointer.
    gating_suite_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("suites.id", ondelete="SET NULL"), nullable=True
    )
    # M1d-5: project-scoped MCP routing override map (precedes workspace override).
    # Shape mirrors ``Workspace.mcp_routing_overrides``:
    # ``{"<target_kind>": "<mcp_provider_name>"}``.
    default_mcp_routing: Mapped[dict[str, Any]] = mapped_column(
        PortableJSON, nullable=False, default=dict, server_default="'{}'"
    )
    # M1d-5: soft-delete tombstone set by DELETE /projects/:id (cascade
    # soft-delete via confirmCascade=true) and cleared by
    # POST /projects/:id/restore. List endpoints filter ``deleted_at IS NULL``
    # by default; admin queries opt-in via ``includeDeleted=true``. 30-day
    # retention then hard-purge sweeper (deferred to M2+).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workspace: Mapped[Workspace] = relationship("Workspace")
    suites: Mapped[list[Suite]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        foreign_keys="Suite.project_id",
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_projects_workspace_slug"),
        # Partial index — fast active-only lookups (M1d-5).
        Index(
            "ix_projects_workspace_active",
            "workspace_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class Suite(Base, TimestampMixin):
    __tablename__ = "suites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2048))
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # M1d: suite-scoped MCP routing override map (precedes workspace override).
    mcp_routing_overrides: Mapped[dict[str, Any]] = mapped_column(
        PortableJSON, nullable=False, default=dict, server_default="'{}'"
    )
    # M1d: soft-delete tombstone set by DELETE /suites/:id (cascade soft-delete
    # via confirmCascade=true) and cleared by POST /suites/:id/restore.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="suites", foreign_keys=[project_id])

    __table_args__ = (
        Index("ix_suites_project_id", "project_id"),
        # Partial index — fast active-only lookups (M1d-4).
        Index(
            "ix_suites_project_active",
            "project_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
