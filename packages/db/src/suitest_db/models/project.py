"""Project + Suite models (docs/DATA_MODEL.md §3.3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id

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

    workspace: Mapped[Workspace] = relationship("Workspace")
    suites: Mapped[list[Suite]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("workspace_id", "slug", name="uq_projects_workspace_slug"),)


class Suite(Base, TimestampMixin):
    __tablename__ = "suites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2048))
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    project: Mapped[Project] = relationship(back_populates="suites")

    __table_args__ = (Index("ix_suites_project_id", "project_id"),)
