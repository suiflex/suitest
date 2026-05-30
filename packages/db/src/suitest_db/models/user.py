"""User + OAuth account models for FastAPI-Users.

Reconciliation note (M1a Task 2a):
  The ``users`` table is owned by FastAPI-Users — the base
  ``SQLAlchemyBaseUserTableUUID`` contributes ``id (UUID, PK)``, ``email``,
  ``hashed_password``, ``is_active``, ``is_superuser``, ``is_verified``. M0
  migrated that base table. M1a *extends* it additively with the Suitest columns
  ``name``, ``avatar_url``, ``created_at``, ``updated_at`` — we do NOT create a
  second users table. Because ``users.id`` is **UUID**, every FK that points at
  it (``memberships.user_id``, ``test_cases.owner_id``, ``defects.assignee_id``,
  ``agent_sessions.user_id``, ``audit_logs.user_id``, ``generator_runs`` /
  ``code_exports.user_id``) is declared as ``UUID`` — not the cuid2 ``String``
  used for every other PK.
"""

import uuid
from datetime import datetime

from fastapi_users.db import SQLAlchemyBaseOAuthAccountTableUUID, SQLAlchemyBaseUserTableUUID
from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from suitest_db.base import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    """Suitest user. UUID PK as required by FastAPI-Users SQLAlchemy adapter."""

    __tablename__ = "users"

    # Suitest-specific additions layered on top of the FastAPI-Users base.
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

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
