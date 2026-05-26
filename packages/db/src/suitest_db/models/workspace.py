"""Workspace model — minimal M0 stub. Full schema lands in M1a (DATA_MODEL.md)."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id


class Workspace(Base, TimestampMixin):
    """Workspace = top-level tenant boundary."""

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
