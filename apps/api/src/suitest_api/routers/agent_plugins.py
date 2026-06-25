"""Agent plugin CRUD endpoints — /api/v1/agent-plugins (M8-1..3).

Surfaces workspace-registered agent definitions plus system plugins discovered
via the ``suitest.plugins`` entry-point group.

Endpoints:
  GET  /agent-plugins          — list workspace definitions + discovered system plugins
  POST /agent-plugins          — register new definition (YAML body), ADMIN/OWNER
  GET  /agent-plugins/{name}   — get one (workspace or system)
  PATCH /agent-plugins/{name}  — update spec, ADMIN/OWNER
  DELETE /agent-plugins/{name} — soft-deactivate, ADMIN/OWNER

System plugins (from PLUGIN_REGISTRY) are returned read-only; workspace definitions
shadow system plugins with the same name on the list endpoint.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_agent.plugin_sdk.base import AgentPluginSpec
from suitest_agent.plugin_sdk.registry import PLUGIN_REGISTRY
from suitest_shared.domain.enums import Role

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.services.agent_definition_service import (
    AgentDefinitionService,
    AgentSpecValidationError,
    DuplicateAgentDefinitionError,
)

router = APIRouter(prefix="/api/v1", tags=["agent-plugins"])

_ADMIN_ROLES = {Role.ADMIN, Role.OWNER}

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AgentDefinitionBody(BaseModel):
    """Request body for POST / PATCH — the raw YAML spec."""

    model_config = ConfigDict(str_strip_whitespace=True)

    spec_yaml: str = Field(
        description="Full AgentPluginSpec serialised as YAML.",
        min_length=10,
    )


class AgentDefinitionRead(BaseModel):
    """Response schema for a single agent definition."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    name: str
    spec_version: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    # Parsed spec fields (convenience denorm)
    spec: AgentPluginSpec | None = None


class SystemPluginRead(BaseModel):
    """Response schema for a system (entry-point-discovered) plugin."""

    source: str = "system"
    spec: AgentPluginSpec


class AgentPluginListResponse(BaseModel):
    """Combined list of workspace definitions and system plugins."""

    workspace_definitions: list[AgentDefinitionRead]
    system_plugins: list[SystemPluginRead]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_spec_safe(spec_yaml: str) -> AgentPluginSpec | None:
    """Return parsed spec or None (for display; validation errors already caught upstream)."""
    try:
        import yaml

        data = yaml.safe_load(spec_yaml)
        if isinstance(data, dict):
            return AgentPluginSpec.model_validate(data)
    except Exception:
        pass
    return None


def _to_read(row: object) -> AgentDefinitionRead:
    """Convert an ORM AgentDefinition row to the response schema."""
    from suitest_db.models.agent_definition import AgentDefinition

    assert isinstance(row, AgentDefinition)
    return AgentDefinitionRead(
        id=row.id,
        workspace_id=row.workspace_id,
        name=row.name,
        spec_version=row.spec_version,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
        spec=_parse_spec_safe(row.spec_yaml),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/agent-plugins", response_model=AgentPluginListResponse)
async def list_agent_plugins(
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> AgentPluginListResponse:
    """List workspace agent definitions and system-discovered plugins."""
    svc = AgentDefinitionService(session)
    ws_rows = await svc.list_definitions(ctx.workspace_id)
    system = [SystemPluginRead(spec=s) for s in PLUGIN_REGISTRY.list_all()]
    return AgentPluginListResponse(
        workspace_definitions=[_to_read(r) for r in ws_rows],
        system_plugins=system,
    )


@router.post(
    "/agent-plugins",
    response_model=AgentDefinitionRead,
    status_code=status.HTTP_201_CREATED,
)
async def register_agent_plugin(
    body: AgentDefinitionBody,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> AgentDefinitionRead:
    """Register a new workspace agent definition from a YAML spec."""
    svc = AgentDefinitionService(session)
    try:
        row = await svc.register_definition(
            workspace_id=ctx.workspace_id,
            spec_yaml=body.spec_yaml,
            user_id=ctx.user_id,
        )
    except AgentSpecValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "AGENT_SPEC_INVALID", "message": exc.detail}},
        ) from exc
    except DuplicateAgentDefinitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "AGENT_DEFINITION_DUPLICATE",
                    "message": str(exc),
                }
            },
        ) from exc
    await session.commit()
    return _to_read(row)


@router.get("/agent-plugins/{name}", response_model=AgentDefinitionRead)
async def get_agent_plugin(
    name: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> AgentDefinitionRead:
    """Return a single workspace agent definition by name."""
    svc = AgentDefinitionService(session)
    row = await svc.get_definition(ctx.workspace_id, name)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {"code": "AGENT_DEFINITION_NOT_FOUND", "message": f"{name!r} not found"}
            },
        )
    return _to_read(row)


@router.patch("/agent-plugins/{name}", response_model=AgentDefinitionRead)
async def update_agent_plugin(
    name: str,
    body: AgentDefinitionBody,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> AgentDefinitionRead:
    """Update the YAML spec for an existing workspace agent definition."""
    svc = AgentDefinitionService(session)
    try:
        row = await svc.update_definition(
            workspace_id=ctx.workspace_id,
            name=name,
            spec_yaml=body.spec_yaml,
            user_id=ctx.user_id,
        )
    except AgentSpecValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "AGENT_SPEC_INVALID", "message": exc.detail}},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {"code": "AGENT_DEFINITION_NOT_FOUND", "message": f"{name!r} not found"}
            },
        ) from exc
    await session.commit()
    return _to_read(row)


@router.delete(
    "/agent-plugins/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_agent_plugin(
    name: str,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Soft-deactivate a workspace agent definition."""
    svc = AgentDefinitionService(session)
    deleted = await svc.deactivate_definition(
        workspace_id=ctx.workspace_id,
        name=name,
        user_id=ctx.user_id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {"code": "AGENT_DEFINITION_NOT_FOUND", "message": f"{name!r} not found"}
            },
        )
    await session.commit()
