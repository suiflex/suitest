"""PluginManifest ORM model (M9-4).

Stores community / official plugin descriptors for the marketplace page.
Rows are seeded by migrations (official plugins) and can be submitted by
community contributors via ``POST /api/v1/plugins/marketplace``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from suitest_db.base import Base
from suitest_db.ids import new_id


class PluginManifest(Base):
    """Marketplace entry for a Suitest plugin.

    ``plugin_type`` values:
    * ``mcp_provider``       — custom MCP server
    * ``reporter``           — test result reporter (XRay, qTest, …)
    * ``integration_adapter`` — issue-tracker / PM tool adapter (Asana, ClickUp, …)
    * ``agent``              — custom agent graph / behaviour
    """

    __tablename__ = "plugin_manifests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    # "mcp_provider" | "reporter" | "integration_adapter" | "agent"
    plugin_type: Mapped[str] = mapped_column(String(40), nullable=False)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    homepage_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # e.g. "pip install suitest-xray-reporter"
    install_command: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_official: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_community: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        Index("ix_plugin_manifests_plugin_type", "plugin_type"),
        UniqueConstraint("name", name="uq_plugin_manifests_name"),
    )
