"""Project read endpoints (docs/API.md §3.2) — workspace-scoped, paginated."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.projects import ProjectRepo
from suitest_shared.schemas.pagination import Page, PageMeta

from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.routers._pagination import decode_cursor_or_400, encode_next
from suitest_api.schemas.project import ProjectPublic

router = APIRouter(prefix="/api/v1", tags=["projects"])


@router.get("/projects", response_model=Page[ProjectPublic])
async def list_projects(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> Page[ProjectPublic]:
    """List the current workspace's projects, keyset-paginated."""
    decoded = decode_cursor_or_400(cursor)
    rows, next_keyset = await ProjectRepo(session).list_by_workspace_paginated(
        ctx.workspace_id, cursor=decoded, limit=limit
    )
    return Page[ProjectPublic](
        items=[ProjectPublic.model_validate(r) for r in rows],
        meta=PageMeta(next_cursor=encode_next(next_keyset), limit=limit),
    )


@router.get("/projects/{project_id}", response_model=ProjectPublic)
async def get_project(
    project_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> ProjectPublic:
    """Return one project; 404 when it does not belong to the active workspace."""
    row = await ProjectRepo(session).get_by_id(project_id)
    if row is None or row.workspace_id != ctx.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    return ProjectPublic.model_validate(row)
