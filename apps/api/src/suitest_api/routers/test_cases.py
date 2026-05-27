"""Test case read endpoints (docs/API.md §3.3) — scoped via suite -> project -> ws.

Each ``TestStepPublic.executable`` is stamped from the workspace's effective tier:
a step is executable when it has explicit ``code`` (deterministic), or the tier is
LOCAL/CLOUD (action -> code translated at run time). The tier is resolved once per
request via :func:`resolve_workspace_tier`.
"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.case import TestStep
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_db.repositories.test_cases import TestCaseRepo
from suitest_shared.domain.enums import CaseSource, CaseStatus, Priority, Tier
from suitest_shared.schemas.pagination import Page, PageMeta

from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.routers._pagination import decode_cursor_or_400, encode_next
from suitest_api.routers._tier import resolve_workspace_tier
from suitest_api.schemas.test_case import TestCaseDetail, TestCaseListItem, TestStepPublic

router = APIRouter(prefix="/api/v1", tags=["test-cases"])


def _step_executable(step: TestStep, tier: Tier) -> bool:
    """Domain rule: executable iff explicit code, or LOCAL/CLOUD with an action."""
    if step.code:
        return True
    return tier in (Tier.LOCAL, Tier.CLOUD) and bool(step.action)


def _step_public(step: TestStep, tier: Tier) -> TestStepPublic:
    return TestStepPublic(
        id=step.id,
        case_id=step.case_id,
        order=step.order,
        action=step.action,
        expected=step.expected,
        code=step.code,
        data=step.data,
        mcp_provider=step.mcp_provider,
        target_kind=step.target_kind,
        executable=_step_executable(step, tier),
    )


async def _suite_in_scope(session: AsyncSession, suite_id: str, workspace_id: str) -> bool:
    suite = await SuiteRepo(session).get_by_id(suite_id)
    if suite is None:
        return False
    project = await ProjectRepo(session).get_by_id(suite.project_id)
    return project is not None and project.workspace_id == workspace_id


@router.get("/test-cases", response_model=Page[TestCaseListItem])
async def list_test_cases(
    suite_id: str = Query(alias="suiteId"),
    status_: CaseStatus | None = Query(default=None, alias="status"),
    source: CaseSource | None = Query(default=None),
    priority: Priority | None = Query(default=None),
    tag: str | None = Query(default=None),
    q: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> Page[TestCaseListItem]:
    """List cases in a suite with filters; 404 when the suite is cross-workspace."""
    if not await _suite_in_scope(session, suite_id, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="suite not found")
    decoded = decode_cursor_or_400(cursor)
    rows, next_keyset = await TestCaseRepo(session).list_by_suite_filtered(
        suite_id,
        status=status_,
        source=source,
        priority=priority,
        tag=tag,
        q=q,
        cursor=decoded,
        limit=limit,
    )
    return Page[TestCaseListItem](
        items=[TestCaseListItem.model_validate(r) for r in rows],
        meta=PageMeta(next_cursor=encode_next(next_keyset), limit=limit),
    )


@router.get("/test-cases/{case_id}", response_model=TestCaseDetail)
async def get_test_case(
    case_id: str,
    request: Request,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> TestCaseDetail:
    """Return a case with its ordered steps (+ executable) and tags; 404 if cross-ws."""
    repo = TestCaseRepo(session)
    case = await repo.get_by_id(case_id)
    if case is None or not await _suite_in_scope(session, case.suite_id, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    tier = await resolve_workspace_tier(request, session, ctx.workspace_id)
    steps = await repo.get_steps(case_id)
    tags = await repo.get_tags(case_id)
    return TestCaseDetail(
        id=case.id,
        suite_id=case.suite_id,
        public_id=case.public_id,
        name=case.name,
        description=case.description,
        preconditions=case.preconditions,
        source=case.source,
        status=case.status,
        priority=case.priority,
        owner_id=case.owner_id,
        created_at=case.created_at,
        updated_at=case.updated_at,
        steps=[_step_public(s, tier) for s in steps],
        tags=tags,
    )


@router.get("/test-cases/{case_id}/steps", response_model=list[TestStepPublic])
async def get_test_case_steps(
    case_id: str,
    request: Request,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[TestStepPublic]:
    """Return a case's steps only (step editor pre-load); 404 when cross-workspace."""
    repo = TestCaseRepo(session)
    case = await repo.get_by_id(case_id)
    if case is None or not await _suite_in_scope(session, case.suite_id, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    tier = await resolve_workspace_tier(request, session, ctx.workspace_id)
    steps: Sequence[TestStep] = await repo.get_steps(case_id)
    return [_step_public(s, tier) for s in steps]
