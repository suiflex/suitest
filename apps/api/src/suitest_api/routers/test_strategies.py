"""Risk-based test strategy endpoints."""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_shared.domain.enums import Role

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.deps.tier import require_llm_ready
from suitest_api.schemas.test_strategy import (
    TestStrategyDraftRequest,
    TestStrategyPublic,
    TestStrategyUpdateRequest,
)
from suitest_api.services.test_strategy_service import (
    TestStrategyLlmError,
    TestStrategyNotFoundError,
    TestStrategyService,
    TestStrategyStateError,
)

router = APIRouter(prefix="/api/v1", tags=["test-strategies"])
_WRITER_ROLES = {Role.QA, Role.ADMIN, Role.OWNER}
_writer_dep = require_role(_WRITER_ROLES)


def _raise_strategy_error(exc: Exception) -> NoReturn:
    if isinstance(exc, TestStrategyNotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, TestStrategyStateError):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, TestStrategyLlmError):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    raise exc


@router.get("/projects/{project_id}/test-strategies", response_model=list[TestStrategyPublic])
async def list_test_strategies(
    project_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[TestStrategyPublic]:
    try:
        return await TestStrategyService(session, ctx).list(project_id)
    except TestStrategyNotFoundError as exc:
        _raise_strategy_error(exc)


@router.post(
    "/projects/{project_id}/test-strategies/draft",
    response_model=TestStrategyPublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_test_strategy_draft(
    project_id: str,
    body: TestStrategyDraftRequest,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> TestStrategyPublic:
    try:
        result = await TestStrategyService(session, ctx).create_draft(project_id, body)
    except TestStrategyNotFoundError as exc:
        _raise_strategy_error(exc)
    await session.commit()
    return result


@router.put("/test-strategies/{strategy_id}", response_model=TestStrategyPublic)
async def update_test_strategy(
    strategy_id: str,
    body: TestStrategyUpdateRequest,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> TestStrategyPublic:
    try:
        result = await TestStrategyService(session, ctx).update(strategy_id, body.document)
    except (TestStrategyNotFoundError, TestStrategyStateError) as exc:
        _raise_strategy_error(exc)
    await session.commit()
    return result


@router.post(
    "/test-strategies/{strategy_id}/enrich",
    response_model=TestStrategyPublic,
    dependencies=[Depends(require_llm_ready)],
)
async def enrich_test_strategy(
    strategy_id: str,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> TestStrategyPublic:
    try:
        result = await TestStrategyService(session, ctx).enrich(strategy_id)
    except (TestStrategyNotFoundError, TestStrategyStateError, TestStrategyLlmError) as exc:
        await session.rollback()
        _raise_strategy_error(exc)
    await session.commit()
    return result


@router.post("/test-strategies/{strategy_id}/approve", response_model=TestStrategyPublic)
async def approve_test_strategy(
    strategy_id: str,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> TestStrategyPublic:
    try:
        result = await TestStrategyService(session, ctx).approve(strategy_id)
    except (TestStrategyNotFoundError, TestStrategyStateError) as exc:
        _raise_strategy_error(exc)
    await session.commit()
    return result
