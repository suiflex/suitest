"""Defect read endpoints (docs/API.md §3.6) — workspace-scoped directly.

Defects carry ``workspace_id``, so scoping is a direct column check. The timeline
is the defect's synthetic ``created`` event followed by its audit_log rows in
ascending time (built by ``DefectRepo.timeline``).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.defects import DefectRepo
from suitest_shared.domain.enums import DefectStatus, Severity
from suitest_shared.schemas.pagination import Page, PageMeta

from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.routers._pagination import decode_cursor_or_400, encode_next
from suitest_api.schemas.defect import (
    DefectDetail,
    DefectListItem,
    DefectTimelineEntry,
    ExternalIssuePublic,
)

router = APIRouter(prefix="/api/v1", tags=["defects"])


@router.get("/defects", response_model=Page[DefectListItem])
async def list_defects(
    status_: DefectStatus | None = Query(default=None, alias="status"),
    severity: Severity | None = Query(default=None),
    assignee_id: uuid.UUID | None = Query(default=None, alias="assigneeId"),
    component: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> Page[DefectListItem]:
    """List the workspace's defects with filters, keyset-paginated."""
    decoded = decode_cursor_or_400(cursor)
    rows, next_keyset = await DefectRepo(session).list_by_workspace(
        ctx.workspace_id,
        status=status_,
        severity=severity,
        assignee_id=assignee_id,
        component=component,
        cursor=decoded,
        limit=limit,
    )
    return Page[DefectListItem](
        items=[DefectListItem.model_validate(r) for r in rows],
        meta=PageMeta(next_cursor=encode_next(next_keyset), limit=limit),
    )


@router.get("/defects/{defect_id}", response_model=DefectDetail)
async def get_defect(
    defect_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> DefectDetail:
    """Return a defect with linked public ids + external issues; 404 if cross-ws."""
    repo = DefectRepo(session)
    defect = await repo.get_by_id(defect_id)
    if defect is None or defect.workspace_id != ctx.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="defect not found")
    case_public, run_public, req_public = await repo.resolve_link_public_ids(defect)
    external = await repo.get_external_issues(defect.id)
    return DefectDetail(
        id=defect.id,
        public_id=defect.public_id,
        workspace_id=defect.workspace_id,
        title=defect.title,
        description=defect.description,
        severity=defect.severity,
        status=defect.status,
        component=defect.component,
        assignee_id=defect.assignee_id,
        agent_diagnosis_kind=defect.agent_diagnosis_kind,
        test_case_public_id=case_public,
        run_public_id=run_public,
        requirement_public_id=req_public,
        external_issues=[ExternalIssuePublic.model_validate(e) for e in external],
        created_at=defect.created_at,
        updated_at=defect.updated_at,
    )


@router.get("/defects/{defect_id}/timeline", response_model=list[DefectTimelineEntry])
async def get_defect_timeline(
    defect_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[DefectTimelineEntry]:
    """Return the defect's creation event + audit rows in ascending time; 404 if cross-ws."""
    repo = DefectRepo(session)
    defect = await repo.get_by_id(defect_id)
    if defect is None or defect.workspace_id != ctx.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="defect not found")
    entries = await repo.timeline(defect_id)
    return [DefectTimelineEntry(at=e.at, action=e.action, actor_id=e.actor_id) for e in entries]
