"""Integration model with AES-GCM-encrypted secrets (docs/DATA_MODEL.md §3.8)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from suitest_core.crypto import EncryptedBytes
from suitest_shared.domain.enums import IntegrationKind

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id
from suitest_db.types import PortableJSON


class Integration(Base, TimestampMixin):
    __tablename__ = "integrations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[IntegrationKind] = mapped_column(
        SAEnum(IntegrationKind, name="integration_kind"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(PortableJSON, nullable=False)

    # secrets stored as AES-GCM blob — see DATA_MODEL §12
    secrets_encrypted: Mapped[str | None] = mapped_column(EncryptedBytes)

    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_integrations_workspace_kind", "workspace_id", "kind"),)
