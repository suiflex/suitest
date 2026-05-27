"""McpProvider — per-workspace MCP server registry (docs/DATA_MODEL.md §4.3)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from suitest_core.crypto import EncryptedBytes
from suitest_shared.domain.enums import McpTransport

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id


class McpProvider(Base, TimestampMixin):
    __tablename__ = "mcp_providers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # browser-use | playwright | api | postgres | kubernetes | graphql | grpc |
    # appium | mongo | mysql | custom
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(1024), nullable=False)
    transport: Mapped[McpTransport] = mapped_column(
        SAEnum(
            McpTransport,
            name="mcp_transport",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    secrets_json_encrypted: Mapped[str | None] = mapped_column(EncryptedBytes)
    # e.g. {"BE_REST": true} → autoroute target_kind BE_REST to this provider
    is_default_for_target: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    health_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_mcp_providers_workspace_kind", "workspace_id", "kind"),
        UniqueConstraint("workspace_id", "name", name="uq_mcp_providers_workspace_name"),
    )
