"""PluginManifest repository (M9-4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.plugin_manifest import PluginManifest
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class PluginManifestCreate(BaseModel):
    name: str
    display_name: str
    description: str = ""
    version: str
    plugin_type: str
    author: str | None = None
    homepage_url: str | None = None
    install_command: str | None = None
    is_official: bool = False
    is_community: bool = True


class PluginManifestUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    version: str | None = None
    author: str | None = None
    homepage_url: str | None = None
    install_command: str | None = None
    is_official: bool | None = None
    is_community: bool | None = None


class PluginManifestRepo(
    AsyncRepository[PluginManifest, PluginManifestCreate, PluginManifestUpdate]
):
    model = PluginManifest

    async def list_all(
        self,
        plugin_type: str | None = None,
    ) -> Sequence[PluginManifest]:
        """Return all manifests, optionally filtered by plugin_type."""
        stmt = select(PluginManifest).order_by(
            PluginManifest.is_official.desc(),
            PluginManifest.name.asc(),
        )
        if plugin_type is not None:
            stmt = stmt.where(PluginManifest.plugin_type == plugin_type)
        return (await self.session.scalars(stmt)).all()

    async def get_by_name(self, name: str) -> PluginManifest | None:
        stmt = select(PluginManifest).where(PluginManifest.name == name)
        result: PluginManifest | None = await self.session.scalar(stmt)
        return result
