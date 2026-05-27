"""Membership — links a User to a Workspace with a Role (docs/DATA_MODEL.md §3.2).

``user_id`` is a UUID FK because ``users.id`` comes from the FastAPI-Users base
(see ``models/user.py``). ``workspace_id`` is a cuid2 string like every other PK.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from suitest_shared.domain.enums import Role

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id
from suitest_db.models.user import User
from suitest_db.models.workspace import Workspace


class Membership(Base, TimestampMixin):
    __tablename__ = "memberships"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[Role] = mapped_column(SAEnum(Role, name="role"), default=Role.QA, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship()

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_memberships_workspace_user"),
        Index("ix_memberships_user_id", "user_id"),
    )
