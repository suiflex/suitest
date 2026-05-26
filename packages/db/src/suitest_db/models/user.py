"""User + OAuth account models for FastAPI-Users."""

import uuid

from fastapi_users.db import SQLAlchemyBaseOAuthAccountTableUUID, SQLAlchemyBaseUserTableUUID
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from suitest_db.base import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    """Suitest user. UUID PK as required by FastAPI-Users SQLAlchemy adapter."""

    __tablename__ = "users"

    oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(
        "OAuthAccount", lazy="joined", cascade="all, delete-orphan"
    )


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    """OAuth account linked to a User."""

    __tablename__ = "oauth_accounts"

    # Override user_id from base because base's FK points to "user.id" (singular)
    # but our users table is plural. Type must be uuid.UUID since users.id is GUID.
    user_id: Mapped[uuid.UUID] = mapped_column(  # type: ignore[assignment]
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
