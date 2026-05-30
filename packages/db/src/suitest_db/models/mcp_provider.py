"""McpProvider — per-workspace MCP server registry (docs/DATA_MODEL.md §4.3)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
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
    # NULL for bundled/global providers; FK to workspace for user-registered
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True
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

    # M1d: provenance / version pins per MCP_PLUGINS §13. All nullable;
    # the resolver writes whichever the transport exposes:
    # stdio → command_pin (+ optional git_ref for git-stdio transports);
    # docker/image → image_pin; SSE/WS → version_pin from handshake.
    command_pin: Mapped[str | None] = mapped_column(String(200))
    image_pin: Mapped[str | None] = mapped_column(String(200))
    version_pin: Mapped[str | None] = mapped_column(String(100))
    git_ref: Mapped[str | None] = mapped_column(String(100))

    health_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # false = registered but not active in routing (e.g. bundled jirac-mcp before integration connect)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # NOTE: Postgres treats NULLs as distinct in unique indexes, so this
    # constraint does not collide on bundled providers (workspace_id IS NULL).
    # Bundled-provider name uniqueness, if desired later, should be enforced
    # via a partial unique idx `(name) WHERE workspace_id IS NULL`.
    __table_args__ = (
        Index("ix_mcp_providers_workspace_kind", "workspace_id", "kind"),
        UniqueConstraint("workspace_id", "name", name="uq_mcp_providers_workspace_name"),
    )
