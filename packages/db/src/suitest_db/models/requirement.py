"""Requirement + RequirementLink (traceability) models (docs/DATA_MODEL.md §3.5)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id


class Requirement(Base, TimestampMixin):
    __tablename__ = "requirements"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # Blocker #3: per-workspace ``public_id`` (REQ-N minted per workspace).
    # Denormalized from the project; filled by the before_insert listener.
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(255))
    external_url: Mapped[str | None] = mapped_column(String(500))
    # M1d-6: soft-delete tombstone. Set by DELETE /requirements/:id, cleared by
    # POST /requirements/:id/restore. List/GET filter ``deleted_at IS NULL``
    # by default. Hard purge sweeper deferred to M2+.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("workspace_id", "public_id", name="uq_requirements_workspace_public_id"),
        Index("ix_requirements_project_id", "project_id"),
        # Partial index — fast active-only lookups (M1d-6).
        Index(
            "ix_requirements_project_active",
            "project_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_requirements_deleted_at", "deleted_at"),
    )


class RequirementLink(Base):
    __tablename__ = "requirement_links"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(
        ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("requirement_id", "case_id", name="uq_requirement_links_req_case"),
    )
