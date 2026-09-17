"""Workspace LLM-readiness and autonomy enforcement dependencies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_core.capabilities import LlmStatus
from suitest_db.repositories.llm_configs import LLMConfigRepo
from suitest_db.repositories.workspace_capabilities import WorkspaceCapabilityRepo
from suitest_shared.domain.enums import AutonomyLevel

from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership

REQUIRES_LLM_ATTR = "__suitest_requires_llm__"


async def workspace_llm_status(session: AsyncSession, workspace_id: str) -> LlmStatus:
    config = await LLMConfigRepo(session).get_active(workspace_id)
    if config is None:
        return LlmStatus.NOT_CONFIGURED
    if config.last_validated_at is None:
        return LlmStatus.VALIDATION_REQUIRED
    return LlmStatus.READY


def _not_ready(current: LlmStatus) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "LLM_NOT_READY",
            "message": "Connect and validate a workspace LLM before using this feature.",
            "llmStatus": current.value,
            "settingsUrl": "/settings?tab=llm",
        },
    )


async def ensure_llm_ready(session: AsyncSession, workspace_id: str) -> None:
    """Raise the shared readiness error unless the workspace LLM is ready."""
    current = await workspace_llm_status(session, workspace_id)
    if current is not LlmStatus.READY:
        raise _not_ready(current)


async def require_llm_ready(
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> TenantContext:
    """FastAPI dependency requiring an active workspace LLM that passed validation."""
    await ensure_llm_ready(session, ctx.workspace_id)
    return ctx


_AUTONOMY_RANK = {
    AutonomyLevel.MANUAL: 0,
    AutonomyLevel.ASSIST: 1,
    AutonomyLevel.SEMI_AUTO: 2,
    AutonomyLevel.AUTO: 3,
}


def require_autonomy(
    minimum: AutonomyLevel,
) -> Callable[..., Awaitable[TenantContext]]:
    """FastAPI dependency enforcing LLM readiness and the workspace autonomy dial."""

    async def _dependency(
        ctx: TenantContext = Depends(require_llm_ready),
        session: AsyncSession = Depends(get_async_session),
    ) -> TenantContext:
        capability = await WorkspaceCapabilityRepo(session).get(ctx.workspace_id)
        current = capability.autonomy_level if capability is not None else AutonomyLevel.MANUAL
        if _AUTONOMY_RANK[current] < _AUTONOMY_RANK[minimum]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "SELF_HEAL_REQUIRES_ASSIST",
                    "message": f"This endpoint requires {minimum.value} autonomy or higher.",
                    "currentAutonomy": current.value,
                },
            )
        return ctx

    return _dependency
