"""Workspace invitation model for invite-only onboarding."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from suitest_shared.domain.enums import Role

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id
from suitest_db.models.user import User
from suitest_db.models.workspace import Workspace


class Invitation(Base, TimestampMixin):
    """Stateful invite token metadata.

    Raw tokens are never stored; ``token_hash`` is SHA-256 over the raw token.
    """

    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[Role] = mapped_column(SAEnum(Role, name="role"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    workspace: Mapped[Workspace] = relationship()
    creator: Mapped[User | None] = relationship()

    __table_args__ = (
        Index("ix_invitations_workspace_id", "workspace_id"),
        Index("ix_invitations_email", "email"),
        Index("ix_invitations_token_hash", "token_hash"),
    )
