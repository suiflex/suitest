"""PromptVersion — versioned agent prompts (docs/DATA_MODEL.md §4.5)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from suitest_db.base import Base
from suitest_db.ids import new_id


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)  # "v1/generate-from-prd"
    version: Mapped[str] = mapped_column(String(32), nullable=False)  # semver
    content: Mapped[str] = mapped_column(Text, nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)  # sha256(content)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_prompt_versions_name_version"),
        Index("ix_prompt_versions_hash", "hash"),
    )
