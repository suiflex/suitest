"""``GET /auth/me`` — current user + memberships (docs/API.md §3.1).

User-scoped (NOT workspace-scoped): it answers "who am I and which workspaces can
I see", so it depends only on ``current_active_user`` + a DB session, never on
``require_workspace_membership``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.user import User
from suitest_db.repositories.workspaces import WorkspaceRepo

from suitest_api.auth.db import get_async_session
from suitest_api.auth.manager import current_active_user
from suitest_api.schemas.workspace import (
    MembershipPublic,
    MeResponse,
    WorkspacePublic,
)

router = APIRouter(prefix="/api/v1", tags=["auth"])


@router.get("/auth/me", response_model=MeResponse)
async def get_me(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> MeResponse:
    """Return the authenticated user plus every workspace membership they hold."""
    memberships = await WorkspaceRepo(session).list_memberships_for_user(user.id)
    return MeResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        must_change_password=user.must_change_password,
        is_superuser=user.is_superuser,
        memberships=[
            MembershipPublic(
                workspace_id=m.workspace_id,
                role=m.role,
                workspace=WorkspacePublic.model_validate(m.workspace),
            )
            for m in memberships
        ],
    )
