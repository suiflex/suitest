"""Multi-tenant scoping — resolve the active :class:`TenantContext` per request.

Every workspace-scoped service takes a ``TenantContext`` so it can constrain
queries to ``ctx.workspace_id``. The context is resolved from the authenticated
user plus the requested workspace, which may arrive via the ``X-Workspace-Id``
header OR the ``workspaceId`` path parameter.

Precedence + validation (M1a):
  * header wins; if BOTH header and path are present and differ → 400.
  * if NEITHER is present → 400 (M1a requires an explicit workspace; we do not
    silently fall back to a "default" workspace).
  * if the workspace exists but the user has no membership in it → 403.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.tenancy import Membership
from suitest_db.models.user import User
from suitest_shared.domain.enums import Role

from suitest_api.auth.db import get_async_session
from suitest_api.auth.manager import current_active_user


@dataclass(frozen=True)
class TenantContext:
    """The resolved tenant boundary for the current request."""

    workspace_id: str
    user_id: str
    role: Role


def _resolve_workspace_id(header_ws: str | None, path_ws: str | None) -> str:
    """Apply header-wins precedence + the M1a 400 rules; return the workspace id."""
    if header_ws is not None and path_ws is not None and header_ws != path_ws:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Workspace-Id header does not match workspaceId path parameter",
        )
    resolved = header_ws or path_ws
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="workspace not specified: pass X-Workspace-Id header or workspaceId path",
        )
    return resolved


async def get_tenant_context(
    request: Request,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
) -> TenantContext:
    """FastAPI dependency: build a :class:`TenantContext` for the request.

    The path workspace is read from ``request.path_params`` (key ``workspaceId``)
    rather than a ``Path(...)`` declaration, because FastAPI path params cannot be
    optional and this dependency is also used on header-only (workspace-less)
    routes. Raises 400 on missing/conflicting workspace, 403 when the user is not
    a member.
    """
    path_ws = request.path_params.get("workspaceId")
    workspace_id_path = path_ws if isinstance(path_ws, str) else None
    workspace_id = _resolve_workspace_id(x_workspace_id, workspace_id_path)
    user_id: uuid.UUID = user.id
    membership = await session.scalar(
        select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == user_id,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user is not a member of the requested workspace",
        )
    return TenantContext(
        workspace_id=workspace_id,
        user_id=str(user_id),
        role=membership.role,
    )


def require_workspace_membership(
    ctx: TenantContext = Depends(get_tenant_context),
) -> TenantContext:
    """Auth + membership gate for all workspace-scoped read routers (Task 7).

    Thin alias over :func:`get_tenant_context`: ``current_active_user`` (via the
    inner dep) yields 401 when unauthenticated, the membership lookup yields 403
    when the user is not a member of the ``X-Workspace-Id`` workspace, and a
    missing header yields 400. Returns the resolved :class:`TenantContext`.
    """
    return ctx
