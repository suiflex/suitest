"""Requirement + traceability read endpoints (docs/API.md §3.7).

All scoped via project -> workspace. The matrix is built from a handful of batched
repo calls (requirements + project cases + project defects + all links) and
assembled in-process — no per-row N+1.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.defects import DefectRepo
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.requirements import RequirementRepo
from suitest_db.repositories.test_cases import TestCaseRepo
from suitest_shared.schemas.pagination import Page, PageMeta

from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.routers._pagination import decode_cursor_or_400, encode_next
from suitest_api.schemas.requirement import (
    MatrixCase,
    MatrixDefect,
    MatrixRequirement,
    RequirementDetail,
    RequirementListItem,
    TraceabilityMatrix,
)

requirements_router = APIRouter(prefix="/api/v1", tags=["requirements"])
traceability_router = APIRouter(prefix="/api/v1", tags=["traceability"])


async def _project_in_scope(session: AsyncSession, project_id: str, workspace_id: str) -> bool:
    project = await ProjectRepo(session).get_by_id(project_id)
    return project is not None and project.workspace_id == workspace_id


@requirements_router.get("/requirements", response_model=Page[RequirementListItem])
async def list_requirements(
    project_id: str = Query(alias="projectId"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> Page[RequirementListItem]:
    """List a project's requirements with link counts; 404 when cross-workspace."""
    if not await _project_in_scope(session, project_id, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    repo = RequirementRepo(session)
    decoded = decode_cursor_or_400(cursor)
    rows, next_keyset = await repo.list_by_project_paginated(
        project_id, cursor=decoded, limit=limit
    )
    counts = await repo.link_counts([r.id for r in rows])
    return Page[RequirementListItem](
        items=[
            RequirementListItem(
                id=r.id,
                project_id=r.project_id,
                public_id=r.public_id,
                title=r.title,
                description=r.description,
                source=r.source,
                external_url=r.external_url,
                link_count=counts.get(r.id, 0),
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ],
        meta=PageMeta(next_cursor=encode_next(next_keyset), limit=limit),
    )


@requirements_router.get("/requirements/{requirement_id}", response_model=RequirementDetail)
async def get_requirement(
    requirement_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> RequirementDetail:
    """Return a requirement with linked case + defect public ids; 404 if cross-ws."""
    repo = RequirementRepo(session)
    req = await repo.get_by_id(requirement_id)
    if req is None or not await _project_in_scope(session, req.project_id, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="requirement not found")
    return RequirementDetail(
        id=req.id,
        project_id=req.project_id,
        public_id=req.public_id,
        title=req.title,
        description=req.description,
        source=req.source,
        external_url=req.external_url,
        case_public_ids=await repo.linked_case_public_ids(req.id),
        defect_public_ids=await repo.linked_defect_public_ids(req.id),
        created_at=req.created_at,
        updated_at=req.updated_at,
    )


@traceability_router.get("/traceability/matrix", response_model=TraceabilityMatrix)
async def traceability_matrix(
    project_id: str = Query(alias="projectId"),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> TraceabilityMatrix:
    """Full traceability grid for a project (docs/API.md §3.7); 404 if cross-ws."""
    if not await _project_in_scope(session, project_id, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")

    req_repo = RequirementRepo(session)
    requirements = await req_repo.list_by_project(project_id)
    cases = await TestCaseRepo(session).list_by_project(project_id)
    defects = await DefectRepo(session).list_by_requirement_project(project_id)
    links = await req_repo.links_by_project(project_id)

    # id -> public_id lookups for cases; requirement -> [case public ids] from links.
    case_public_by_id = {c.id: c.public_id for c in cases}
    tests_by_req: dict[str, list[str]] = {r.id: [] for r in requirements}
    for link in links:
        public = case_public_by_id.get(link.case_id)
        if public is not None:
            tests_by_req.setdefault(link.requirement_id, []).append(public)
    defects_by_req: dict[str, list[str]] = {r.id: [] for r in requirements}
    for d in defects:
        if d.requirement_id is not None:
            defects_by_req.setdefault(d.requirement_id, []).append(d.public_id)

    return TraceabilityMatrix(
        requirements=[
            MatrixRequirement(
                id=r.public_id,
                title=r.title,
                tests=sorted(tests_by_req.get(r.id, [])),
                defects=sorted(defects_by_req.get(r.id, [])),
            )
            for r in requirements
        ],
        cases=[
            MatrixCase(id=c.public_id, name=c.name, source=c.source, status=c.status) for c in cases
        ],
        defects=[
            MatrixDefect(id=d.public_id, title=d.title, severity=d.severity, status=d.status)
            for d in defects
        ],
    )
