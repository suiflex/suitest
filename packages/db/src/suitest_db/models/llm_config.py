"""LLMConfig model — workspace LLM provider with encrypted key (docs/DATA_MODEL.md §4.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from suitest_core.crypto import EncryptedBytes

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id
from suitest_db.types import PortableJSON


class LLMConfig(Base, TimestampMixin):
    __tablename__ = "llm_configs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)

    # AES-GCM (DATA_MODEL §12). Nullable so ZERO tier can store a row with no key.
    api_key_encrypted: Mapped[str | None] = mapped_column(EncryptedBytes)

    config_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_llm_configs_workspace_active", "workspace_id", "is_active"),)
