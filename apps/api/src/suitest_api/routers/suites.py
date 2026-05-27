"""Suite read endpoints (docs/API.md §3.4) — scoped via project -> workspace.

A suite has no ``workspace_id``; scope is enforced by checking the parent
project belongs to the active workspace. Each ``SuitePublic`` carries a computed
``case_count`` (non-deleted cases), batched via one grouped query to avoid N+1.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.suites import SuiteRepo

from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.schemas.project import SuitePublic

router = APIRouter(prefix="/api/v1", tags=["suites"])


async def _project_in_scope(repo: ProjectRepo, project_id: str, workspace_id: str) -> bool:
    project = await repo.get_by_id(project_id)
    return project is not None and project.workspace_id == workspace_id


@router.get("/suites", response_model=list[SuitePublic])
async def list_suites(
    project_id: str = Query(alias="projectId"),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[SuitePublic]:
    """List suites for a project; 404 when the project is cross-workspace."""
    project_repo = ProjectRepo(session)
    if not await _project_in_scope(project_repo, project_id, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    suite_repo = SuiteRepo(session)
    rows = await suite_repo.list_by_project(project_id)
    counts = await suite_repo.case_counts([s.id for s in rows])
    return [
        SuitePublic(
            id=s.id,
            project_id=s.project_id,
            name=s.name,
            description=s.description,
            order=s.order,
            case_count=counts.get(s.id, 0),
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in rows
    ]


@router.get("/suites/{suite_id}", response_model=SuitePublic)
async def get_suite(
    suite_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> SuitePublic:
    """Return one suite with its case_count; 404 when cross-workspace."""
    suite_repo = SuiteRepo(session)
    suite = await suite_repo.get_by_id(suite_id)
    if suite is None or not await _project_in_scope(
        ProjectRepo(session), suite.project_id, ctx.workspace_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="suite not found")
    counts = await suite_repo.case_counts([suite.id])
    return SuitePublic(
        id=suite.id,
        project_id=suite.project_id,
        name=suite.name,
        description=suite.description,
        order=suite.order,
        case_count=counts.get(suite.id, 0),
        created_at=suite.created_at,
        updated_at=suite.updated_at,
    )
