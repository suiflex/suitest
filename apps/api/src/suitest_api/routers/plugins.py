"""Plugin marketplace + discovery endpoints (M9-4).

Routes
------
GET  /api/v1/plugins/marketplace            list all PluginManifest rows (public)
GET  /api/v1/plugins/marketplace/{name}     get one manifest (public)
POST /api/v1/plugins/marketplace            submit a new manifest (ADMIN/OWNER)
GET  /api/v1/plugins/reporters              list registered reporters
GET  /api/v1/plugins/integration-adapters   list custom integration adapter kinds
GET  /api/v1/plugins/mcp-providers          list discovered custom MCP providers

The marketplace read endpoints are intentionally unauthenticated so OSS users
can browse available plugins without logging in.  The POST (submit) endpoint
requires ADMIN or OWNER role because we don't yet have a community review queue.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.plugin_manifests import (
    PluginManifestCreate,
    PluginManifestRepo,
)
from suitest_shared.domain.enums import Role

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext
from suitest_api.services.custom_integration_service import (
    custom_integration_adapter_registry,
)
from suitest_api.services.reporter_registry import reporter_registry

router = APIRouter(prefix="/api/v1/plugins", tags=["plugins"])

_ADMIN_ROLES: set[Role] = {Role.ADMIN, Role.OWNER}
_admin_dep = require_role(_ADMIN_ROLES)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class PluginManifestOut(BaseModel):
    id: str
    name: str
    display_name: str
    description: str
    version: str
    plugin_type: str
    author: str | None
    homepage_url: str | None
    install_command: str | None
    is_official: bool
    is_community: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PluginManifestSubmit(BaseModel):
    name: str
    display_name: str
    description: str = ""
    version: str
    plugin_type: str
    author: str | None = None
    homepage_url: str | None = None
    install_command: str | None = None


class ReporterInfo(BaseModel):
    name: str


class IntegrationAdapterInfo(BaseModel):
    kind: str


class CustomMcpProviderInfo(BaseModel):
    name: str
    transport: str
    version: str | None = None


# ---------------------------------------------------------------------------
# Marketplace endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/marketplace",
    response_model=list[PluginManifestOut],
    summary="List all plugin manifests (public)",
)
async def list_marketplace(
    plugin_type: str | None = Query(default=None, description="Filter by plugin_type"),
    session: AsyncSession = Depends(get_async_session),
) -> list[PluginManifestOut]:
    """Return all registered plugin manifests, optionally filtered by type."""
    rows = await PluginManifestRepo(session).list_all(plugin_type=plugin_type)
    return [PluginManifestOut.model_validate(r) for r in rows]


@router.get(
    "/marketplace/{name}",
    response_model=PluginManifestOut,
    summary="Get one plugin manifest by name (public)",
)
async def get_marketplace_entry(
    name: str,
    session: AsyncSession = Depends(get_async_session),
) -> PluginManifestOut:
    """Return a single plugin manifest by its unique name."""
    row = await PluginManifestRepo(session).get_by_name(name)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"plugin {name!r} not found",
        )
    return PluginManifestOut.model_validate(row)


@router.post(
    "/marketplace",
    response_model=PluginManifestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new plugin manifest (ADMIN/OWNER)",
)
async def submit_marketplace_entry(
    body: PluginManifestSubmit,
    ctx: TenantContext = Depends(_admin_dep),
    session: AsyncSession = Depends(get_async_session),
) -> PluginManifestOut:
    """Register a new community plugin manifest.

    Only ADMIN or OWNER can submit.  Name must be globally unique.
    """
    existing = await PluginManifestRepo(session).get_by_name(body.name)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"plugin {body.name!r} already exists",
        )
    dto = PluginManifestCreate(
        name=body.name,
        display_name=body.display_name,
        description=body.description,
        version=body.version,
        plugin_type=body.plugin_type,
        author=body.author,
        homepage_url=body.homepage_url,
        install_command=body.install_command,
        is_official=False,
        is_community=True,
    )
    row = await PluginManifestRepo(session).create(dto)
    await session.commit()
    await session.refresh(row)
    return PluginManifestOut.model_validate(row)


# ---------------------------------------------------------------------------
# In-process registry introspection endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/reporters",
    response_model=list[ReporterInfo],
    summary="List registered reporter plugins",
)
async def list_reporters() -> list[ReporterInfo]:
    """Return the names of all registered reporter plugin instances."""
    return [ReporterInfo(name=n) for n in reporter_registry.list_all()]


@router.get(
    "/integration-adapters",
    response_model=list[IntegrationAdapterInfo],
    summary="List custom integration adapter kinds",
)
async def list_integration_adapters() -> list[IntegrationAdapterInfo]:
    """Return the kinds of all registered custom integration adapters."""
    return [IntegrationAdapterInfo(kind=k) for k in custom_integration_adapter_registry.list_all()]


@router.get(
    "/mcp-providers",
    response_model=list[CustomMcpProviderInfo],
    summary="List discovered custom MCP entry-point providers",
)
async def list_custom_mcp_providers() -> list[CustomMcpProviderInfo]:
    """Return custom MCP providers discovered via the suitest.mcp_providers entry group."""
    from suitest_mcp.entrypoints.loader import discover_custom_mcp_providers

    classes = discover_custom_mcp_providers()
    return [
        CustomMcpProviderInfo(
            name=cls.spec.name,
            transport=cls.spec.transport,
            version=cls.spec.version,
        )
        for cls in classes
    ]
