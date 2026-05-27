"""Workspace model — top-level tenant boundary (docs/DATA_MODEL.md §3.2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id

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

    memberships: Mapped[list[Membership]] = relationship(
        "Membership", back_populates="workspace", cascade="all, delete-orphan"
    )
