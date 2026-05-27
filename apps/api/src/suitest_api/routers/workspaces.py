"""Workspace read endpoints (docs/API.md §3.1).

``GET /workspaces`` is user-scoped (lists only the caller's workspaces). The
detail + members routes verify membership inline and return **403** for a
non-member (the workspace exists but is not visible to the caller).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.user import User
from suitest_db.repositories.workspaces import WorkspaceRepo

from suitest_api.auth.db import get_async_session
from suitest_api.auth.manager import current_active_user
from suitest_api.schemas.workspace import (
    WorkspaceDetail,
    WorkspaceMemberPublic,
    WorkspacePublic,
)

router = APIRouter(prefix="/api/v1", tags=["workspaces"])


async def _membership_or_403(repo: WorkspaceRepo, *, workspace_id: str, user: User) -> None:
    """Raise 403 unless ``user`` is a member of ``workspace_id``."""
    memberships = await repo.list_memberships_for_user(user.id)
    if not any(m.workspace_id == workspace_id for m in memberships):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user is not a member of the requested workspace",
        )


@router.get("/workspaces", response_model=list[WorkspacePublic])
async def list_workspaces(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[WorkspacePublic]:
    """List the workspaces the current user is a member of."""
    rows = await WorkspaceRepo(session).list_for_user(user.id)
    return [WorkspacePublic.model_validate(r) for r in rows]


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceDetail)
async def get_workspace(
    workspace_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> WorkspaceDetail:
    """Return one workspace; 403 when the caller is not a member."""
    repo = WorkspaceRepo(session)
    await _membership_or_403(repo, workspace_id=workspace_id, user=user)
    row = await repo.get_by_id(workspace_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace not found")
    return WorkspaceDetail.model_validate(row)


@router.get("/workspaces/{workspace_id}/members", response_model=list[WorkspaceMemberPublic])
async def list_workspace_members(
    workspace_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[WorkspaceMemberPublic]:
    """List all members of a workspace; 403 when the caller is not a member."""
    repo = WorkspaceRepo(session)
    await _membership_or_403(repo, workspace_id=workspace_id, user=user)
    members = await repo.list_members(workspace_id)
    return [
        WorkspaceMemberPublic(
            user_id=m.user.id,
            email=m.user.email,
            name=m.user.name,
            role=m.role,
            joined_at=m.created_at,
        )
        for m in members
    ]
