"""Resolve a workspace's effective capability tier inside a request.

Used by endpoints that must reason about the tier without returning the full
``/capabilities`` payload — notably the test-case reader, which stamps each step's
``executable`` flag (``TestStep.executable(tier)``). Mirrors the same base + overlay
precedence as the ``/capabilities`` endpoint: active LLMConfig > WorkspaceCapability
> env base.
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.llm_configs import LLMConfigRepo
from suitest_db.repositories.workspace_capabilities import WorkspaceCapabilityRepo
from suitest_shared.domain.enums import Tier
from suitest_shared.schemas.capabilities import Capabilities

from suitest_api.capabilities import build_base_capabilities, build_workspace_overlay


def _base(request: Request) -> Capabilities:
    cached = getattr(request.app.state, "capabilities", None)
    if isinstance(cached, Capabilities):
        return cached
    return build_base_capabilities()


async def resolve_workspace_tier(
    request: Request, session: AsyncSession, workspace_id: str
) -> Tier:
    """Return the effective :class:`Tier` for ``workspace_id`` (base + DB overlay)."""
    base = _base(request)
    workspace_capability = await WorkspaceCapabilityRepo(session).get(workspace_id)
    active_llm_config = await LLMConfigRepo(session).get_active(workspace_id)
    overlaid = build_workspace_overlay(
        base,
        workspace_capability=workspace_capability,
        active_llm_config=active_llm_config,
        mcp_providers=[],
    )
    return overlaid.tier
