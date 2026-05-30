"""Password reset request review model for pre-SMTP deployments."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column
from suitest_core.crypto import EncryptedBytes

from suitest_db.base import Base
from suitest_db.ids import new_id


class PasswordResetRequest(Base):
    """Stores reset-token metadata for super-admin review."""

    __tablename__ = "password_reset_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    reset_link_encrypted: Mapped[str | None] = mapped_column(EncryptedBytes)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_password_reset_requests_email", "email"),
        Index("ix_password_reset_requests_token_hash", "token_hash"),
    )
