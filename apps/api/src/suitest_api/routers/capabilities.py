"""Public workspace capability discovery.

The workspace header selects the active LLM configuration. Unknown or absent
workspace ids return the unauthenticated base used by the login page.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.llm_configs import LLMConfigRepo
from suitest_db.repositories.mcp_providers import McpProviderRepo
from suitest_db.repositories.workspace_capabilities import WorkspaceCapabilityRepo
from suitest_db.repositories.workspaces import WorkspaceRepo
from suitest_shared.schemas.capabilities import Capabilities

from suitest_api.auth.db import get_async_session
from suitest_api.capabilities import build_base_capabilities, build_workspace_overlay

router = APIRouter(tags=["meta"])


def _base_capabilities(request: Request) -> Capabilities:
    """Return the startup-resolved base capabilities, recomputing if unset.

    ``app.state.capabilities`` is populated by the lifespan hook; the fallback
    keeps the endpoint working if it is ever queried outside a managed lifespan.
    """
    cached = getattr(request.app.state, "capabilities", None)
    if isinstance(cached, Capabilities):
        return cached
    return build_base_capabilities()


@router.get("/capabilities", response_model=Capabilities, response_model_by_alias=True)
async def get_capabilities(
    request: Request,
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    session: AsyncSession = Depends(get_async_session),
) -> Capabilities:
    """Return the resolved capabilities, overlaying workspace config when present."""
    base = _base_capabilities(request)
    if not x_workspace_id:
        return base

    workspace = await WorkspaceRepo(session).get_by_id(x_workspace_id)
    if workspace is None:
        return base

    workspace_capability = await WorkspaceCapabilityRepo(session).get(x_workspace_id)
    active_llm_config = await LLMConfigRepo(session).get_active(x_workspace_id)
    mcp_providers = await McpProviderRepo(session).list_by_workspace(x_workspace_id)
    return build_workspace_overlay(
        base,
        workspace_capability=workspace_capability,
        active_llm_config=active_llm_config,
        mcp_providers=mcp_providers,
    )


@router.get("/capabilities/health", response_model_by_alias=True)
async def get_capabilities_health(request: Request) -> dict[str, object]:
    """Lightweight process liveness probe."""
    started_at = getattr(request.app.state, "started_at", None)
    uptime = int(time.monotonic() - started_at) if isinstance(started_at, float) else 0
    return {"status": "ok", "uptimeSec": uptime}
