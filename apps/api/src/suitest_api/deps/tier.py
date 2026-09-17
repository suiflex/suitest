"""Workspace LLM-readiness and autonomy enforcement decorators."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_core.capabilities import LlmStatus
from suitest_db.repositories.llm_configs import LLMConfigRepo
from suitest_db.repositories.workspace_capabilities import WorkspaceCapabilityRepo
from suitest_shared.domain.enums import AutonomyLevel

from suitest_api.deps.scope import TenantContext

P = ParamSpec("P")
R = TypeVar("R")

REQUIRES_LLM_ATTR = "__suitest_requires_llm__"


def _dependencies(
    args: tuple[object, ...], kwargs: dict[str, object]
) -> tuple[TenantContext, AsyncSession]:
    ctx = kwargs.get("ctx")
    session = kwargs.get("session")
    if args:
        owner = args[0]
        ctx = ctx or getattr(owner, "_ctx", None)
        session = session or getattr(owner, "_session", None)
    if not isinstance(ctx, TenantContext) or not isinstance(session, AsyncSession):
        raise RuntimeError("LLM-gated endpoint requires ctx and session dependencies")
    return ctx, session


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


def require_llm_ready[**P, R](fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Require an active workspace LLM that passed connection validation."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        ctx, session = _dependencies(tuple(args), dict(kwargs))
        await ensure_llm_ready(session, ctx.workspace_id)
        return await fn(*args, **kwargs)

    setattr(wrapper, REQUIRES_LLM_ATTR, True)
    return wrapper


_AUTONOMY_RANK = {
    AutonomyLevel.MANUAL: 0,
    AutonomyLevel.ASSIST: 1,
    AutonomyLevel.SEMI_AUTO: 2,
    AutonomyLevel.AUTO: 3,
}


def require_autonomy(
    minimum: AutonomyLevel,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Enforce LLM readiness and the workspace autonomy dial."""

    def decorator(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            ctx, session = _dependencies(tuple(args), dict(kwargs))
            current_llm = await workspace_llm_status(session, ctx.workspace_id)
            if current_llm is not LlmStatus.READY:
                raise _not_ready(current_llm)
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
            return await fn(*args, **kwargs)

        return wrapper

    return decorator
