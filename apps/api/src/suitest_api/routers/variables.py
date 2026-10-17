"""Workspace & Suite variables and credentials router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_shared.domain.enums import Role

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.schemas.variable import (
    ResolvedVariableItem,
    VariableCreate,
    VariablePublic,
    VariableUpdate,
)
from suitest_api.services.variable_service import VariableService

router = APIRouter(prefix="/api/v1", tags=["variables"])

_WRITER_ROLES: set[Role] = {Role.QA, Role.ADMIN, Role.OWNER}
_writer_dep = require_role(_WRITER_ROLES)


async def _resolve_suite_workspace(
    suite_id: str,
    session: AsyncSession,
) -> tuple[str, str]:
    """Verify suite exists and return (suite_id, workspace_id)."""
    suite_repo = SuiteRepo(session)
    project_repo = ProjectRepo(session)

    suite = await suite_repo.get_by_id(suite_id)
    if suite is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suite not found",
        )
    project = await project_repo.get_by_id(suite.project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parent project not found",
        )
    return suite.id, project.workspace_id


# --- Workspace Variables Endpoints ------------------------------------------


@router.get(
    "/workspaces/{workspace_id}/variables",
    response_model=list[VariablePublic],
)
async def list_workspace_variables(
    workspace_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[VariablePublic]:
    if ctx.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    service = VariableService(session)
    return await service.list_workspace_variables(workspace_id)


@router.post(
    "/workspaces/{workspace_id}/variables",
    response_model=VariablePublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_writer_dep)],
)
async def create_workspace_variable(
    workspace_id: str,
    body: VariableCreate,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> VariablePublic:
    if ctx.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    service = VariableService(session)
    result = await service.create_workspace_variable(workspace_id, body)
    await session.commit()
    return result


@router.patch(
    "/workspaces/{workspace_id}/variables/{var_id}",
    response_model=VariablePublic,
    dependencies=[Depends(_writer_dep)],
)
async def update_workspace_variable(
    workspace_id: str,
    var_id: str,
    body: VariableUpdate,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> VariablePublic:
    if ctx.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    service = VariableService(session)
    updated = await service.update_workspace_variable(workspace_id, var_id, body)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Variable not found")
    await session.commit()
    return updated


@router.delete(
    "/workspaces/{workspace_id}/variables/{var_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(_writer_dep)],
)
async def delete_workspace_variable(
    workspace_id: str,
    var_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    if ctx.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    service = VariableService(session)
    deleted = await service.delete_workspace_variable(workspace_id, var_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Variable not found")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/workspaces/{workspace_id}/variables/resolved",
    response_model=list[ResolvedVariableItem],
)
@router.get(
    "/workspaces/{workspace_id}/variables/resolve",
    response_model=list[ResolvedVariableItem],
    include_in_schema=False,
)
async def get_resolved_workspace_variables(
    workspace_id: str,
    suite_id: str | None = None,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[ResolvedVariableItem]:
    if ctx.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    service = VariableService(session)
    return await service.resolve_hierarchy(workspace_id, suite_id, include_secrets=False)


# --- Suite Variables Endpoints ----------------------------------------------


@router.get(
    "/suites/{suite_id}/variables",
    response_model=list[VariablePublic],
)
async def list_suite_variables(
    suite_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[VariablePublic]:
    _, ws_id = await _resolve_suite_workspace(suite_id, session)
    if ctx.workspace_id != ws_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    service = VariableService(session)
    return await service.list_suite_variables(suite_id)


@router.post(
    "/suites/{suite_id}/variables",
    response_model=VariablePublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_writer_dep)],
)
async def create_suite_variable(
    suite_id: str,
    body: VariableCreate,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> VariablePublic:
    _, ws_id = await _resolve_suite_workspace(suite_id, session)
    if ctx.workspace_id != ws_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    service = VariableService(session)
    result = await service.create_suite_variable(suite_id, body)
    await session.commit()
    return result


@router.patch(
    "/suites/{suite_id}/variables/{var_id}",
    response_model=VariablePublic,
    dependencies=[Depends(_writer_dep)],
)
async def update_suite_variable(
    suite_id: str,
    var_id: str,
    body: VariableUpdate,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> VariablePublic:
    _, ws_id = await _resolve_suite_workspace(suite_id, session)
    if ctx.workspace_id != ws_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    service = VariableService(session)
    updated = await service.update_suite_variable(suite_id, var_id, body)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Variable not found")
    await session.commit()
    return updated


@router.delete(
    "/suites/{suite_id}/variables/{var_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(_writer_dep)],
)
async def delete_suite_variable(
    suite_id: str,
    var_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    _, ws_id = await _resolve_suite_workspace(suite_id, session)
    if ctx.workspace_id != ws_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    service = VariableService(session)
    deleted = await service.delete_suite_variable(suite_id, var_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Variable not found")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/suites/{suite_id}/variables/resolved",
    response_model=list[ResolvedVariableItem],
)
async def get_resolved_suite_variables(
    suite_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[ResolvedVariableItem]:
    _, ws_id = await _resolve_suite_workspace(suite_id, session)
    if ctx.workspace_id != ws_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    service = VariableService(session)
    # Public route returns masked secrets for security (UI hover / preview)
    return await service.resolve_hierarchy(ws_id, suite_id, include_secrets=False)
