"""MCP providers read endpoint — Integrations screen MCP tab (docs/API.md §3.10).

Workspace-scoped, secrets never surfaced (the model's ``secrets_json_encrypted``
column is intentionally NOT decrypted by this read path — only the names + health
status reach the response). CRUD lands in M2 alongside the MCP runner; M1b ships
the list path so the Integrations screen renders against the real DB instead of
MSW.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.mcp_providers import McpProviderRepo

from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership

router = APIRouter(prefix="/api/v1", tags=["mcp"])


class McpProviderPublic(BaseModel):
    """One MCP provider row — name + transport + health only (no secrets)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    kind: str
    transport: str
    endpoint: str
    health_status: str = Field(default="unknown", alias="healthStatus")
    last_health_at: datetime | None = Field(default=None, alias="lastHealthAt")
    is_bundled: bool = Field(default=False, alias="isBundled")


class McpProvidersResponse(BaseModel):
    """``GET /mcp/providers`` envelope (read-only in M1b)."""

    items: list[McpProviderPublic] = Field(default_factory=list)


@router.get("/mcp/providers", response_model=McpProvidersResponse)
async def list_mcp_providers(
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> McpProvidersResponse:
    """List MCP providers for the workspace (read-only in M1b; CRUD in M2)."""
    rows = await McpProviderRepo(session).list_by_workspace(workspace_id=ctx.workspace_id)
    return McpProvidersResponse(
        items=[
            McpProviderPublic(
                id=r.id,
                name=r.name,
                kind=r.kind,
                # Enum or plain str — both pass through ``str(...)`` cleanly.
                transport=r.transport.value if hasattr(r.transport, "value") else str(r.transport),
                endpoint=r.endpoint,
                health_status=r.health_status,
                last_health_at=r.last_health_at,
                # ``is_bundled`` ships as a column in M2; default False until then.
                is_bundled=False,
            )
            for r in rows
        ]
    )
