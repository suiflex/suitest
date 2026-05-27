"""McpProvider repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.mcp_provider import McpProvider
from suitest_db.repositories.base import AsyncRepository
from suitest_shared.domain.enums import McpTransport

if TYPE_CHECKING:
    from collections.abc import Sequence


class McpProviderCreate(BaseModel):
    workspace_id: str
    name: str
    kind: str
    endpoint: str
    transport: McpTransport
    config_json: dict[str, object] | None = None
    secrets_json_encrypted: str | None = None
    is_default_for_target: dict[str, object] | None = None


class McpProviderUpdate(BaseModel):
    name: str | None = None
    kind: str | None = None
    endpoint: str | None = None
    transport: McpTransport | None = None
    config_json: dict[str, object] | None = None
    secrets_json_encrypted: str | None = None
    is_default_for_target: dict[str, object] | None = None
    health_status: str | None = None


class McpProviderRepo(AsyncRepository[McpProvider, McpProviderCreate, McpProviderUpdate]):
    model = McpProvider

    async def list_by_workspace(self, workspace_id: str) -> Sequence[McpProvider]:
        stmt = (
            select(McpProvider)
            .where(McpProvider.workspace_id == workspace_id)
            .order_by(McpProvider.created_at.desc(), McpProvider.id.desc())
        )
        return (await self.session.scalars(stmt)).all()

    async def get_by_name(self, workspace_id: str, name: str) -> McpProvider | None:
        stmt = select(McpProvider).where(
            McpProvider.workspace_id == workspace_id, McpProvider.name == name
        )
        result: McpProvider | None = await self.session.scalar(stmt)
        return result
