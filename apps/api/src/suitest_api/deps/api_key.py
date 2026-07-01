"""API-key authentication — lets MCP / SDK / CI clients reach a workspace.

Two dependencies:

* :func:`require_api_key` — key-only routes (e.g. the ``whoami`` verify probe).
* :func:`tenant_via_api_key_or_session` — accepts EITHER a session cookie/JWT OR
  an ``sk_suitest_`` key, so the same programmatic endpoint works for a logged-in
  human and for a machine holding a key.

Security: a key is bound to exactly ONE workspace (its ``workspace_id``). When a
request authenticates with a key we IGNORE any client-supplied workspace and pin
the tenant to the key's workspace — and reject a mismatching ``X-Workspace-Id``
outright. A key therefore can never touch another workspace's data, and a
revoked/expired key resolves to nothing (401). Keys act with the least-privilege
``QA`` role: they can run tests and ingest results, never manage members or keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.tenancy import Membership
from suitest_shared.domain.enums import Role

from suitest_api.auth.db import get_async_session
from suitest_api.auth.manager import current_active_user_optional
from suitest_api.deps.scope import TenantContext, _resolve_workspace_id
from suitest_api.services.api_key_service import KEY_PREFIX, authenticate

if TYPE_CHECKING:
    from suitest_db.models.user import User


@dataclass(frozen=True)
class ApiKeyPrincipal:
    """The identity a valid API key resolves to."""

    workspace_id: str
    user_id: str | None
    key_id: str
    key_name: str


def _extract_token(request: Request, x_api_key: str | None) -> str | None:
    """Pull an ``sk_suitest_`` token from ``X-API-Key`` or ``Authorization: Bearer``."""
    if x_api_key and x_api_key.startswith(KEY_PREFIX):
        return x_api_key
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        candidate = auth[7:].strip()
        if candidate.startswith(KEY_PREFIX):
            return candidate
    return None


async def resolve_api_key_principal(
    request: Request,
    session: AsyncSession,
    x_api_key: str | None,
) -> ApiKeyPrincipal | None:
    """Return the principal for a valid key, or ``None`` (no token / invalid)."""
    token = _extract_token(request, x_api_key)
    if token is None:
        return None
    row = await authenticate(session, token)
    if row is None:
        return None
    return ApiKeyPrincipal(
        workspace_id=row.workspace_id,
        user_id=str(row.created_by) if row.created_by is not None else None,
        key_id=row.id,
        key_name=row.name,
    )


async def require_api_key(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> ApiKeyPrincipal:
    """Key-only gate: 401 unless a live ``sk_suitest_`` key is presented."""
    principal = await resolve_api_key_principal(request, session, x_api_key)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="valid API key required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


async def tenant_via_api_key_or_session(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    user: User | None = Depends(current_active_user_optional),
) -> TenantContext:
    """Resolve the tenant from an API key (preferred) or the session user."""
    principal = await resolve_api_key_principal(request, session, x_api_key)
    if principal is not None:
        # A key is pinned to its own workspace — reject a conflicting header so a
        # client can never trick a key into another tenant.
        if x_workspace_id is not None and x_workspace_id != principal.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key is not valid for the requested workspace",
            )
        return TenantContext(
            workspace_id=principal.workspace_id,
            user_id=principal.user_id or principal.key_id,
            role=Role.QA,
        )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required: sign in or supply an API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    path_ws = request.path_params.get("workspaceId")
    workspace_id = _resolve_workspace_id(
        x_workspace_id, path_ws if isinstance(path_ws, str) else None
    )
    membership = await session.scalar(
        select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == user.id,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user is not a member of the requested workspace",
        )
    return TenantContext(workspace_id=workspace_id, user_id=str(user.id), role=membership.role)
