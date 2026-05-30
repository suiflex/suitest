"""Audit log read endpoint — workspace-scoped audit trail (M1d-27).

Implements ``GET /audit-logs`` per ``docs/API.md §146-158`` with cursor
pagination (opaque base64 of ``(created_at, id)``), full filter set
(``action`` glob, ``resource_type`` exact, ``user_id`` exact, ``from`` / ``to``
inclusive datetime range, ``limit`` ≤ 200), and ADMIN+ role gating.

ZERO-tier compatible — no ``require_tier(...)`` introduced. Cross-workspace
isolation is enforced by ``require_workspace_membership`` (only resolves the
tenant context after a membership lookup on ``X-Workspace-Id``); the repository
query additionally constrains every row to ``ctx.workspace_id`` so a cursor
forged from another workspace's row simply returns an empty page rather than
leaking data.

The Dashboard agent-activity feed (pre-M1d) used the same path with a small
bounded list; that surface is now satisfied by ``GET /audit-logs?action=agent.*``
with ADMIN+ role. The legacy small-list shape is gone — every caller now
receives ``{items, next_cursor}``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, status
from suitest_shared.domain.enums import Role

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.routers._pagination import decode_cursor_or_400, encode_next
from suitest_api.schemas.audit_log import AuditLogsResponse
from suitest_api.services.audit_log_service import AuditLogService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1", tags=["audit"])

# Per docs/API.md §163 — ``GET /audit-logs`` is ADMIN+ only.
_AUDIT_READ_ROLES: set[Role] = {Role.ADMIN, Role.OWNER}

# Hard cap from docs/API.md §161. Out-of-range ``limit`` is a 400, not a clamp,
# so the client never silently truncates a page it asked to be larger.
_LIMIT_MIN = 1
_LIMIT_MAX = 200
_LIMIT_DEFAULT = 50


@router.get(
    "/audit-logs",
    response_model=AuditLogsResponse,
    dependencies=[Depends(require_role(_AUDIT_READ_ROLES))],
)
async def list_audit_logs(
    cursor: str | None = Query(default=None, description="Opaque cursor from a prior page."),
    action: str | None = Query(default=None, description="Glob filter (e.g. 'integration.*')."),
    resource_type: str | None = Query(default=None, description="Exact resource_type filter."),
    user_id: str | None = Query(default=None, description="Exact UUID actor filter."),
    from_: datetime | None = Query(
        default=None, alias="from", description="ISO-8601 lower bound (inclusive)."
    ),
    to: datetime | None = Query(default=None, description="ISO-8601 upper bound (inclusive)."),
    limit: int = Query(default=_LIMIT_DEFAULT, description="Page size; 1..200, default 50."),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> AuditLogsResponse:
    """List workspace audit rows newest-first with cursor pagination + filters."""
    if limit < _LIMIT_MIN or limit > _LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"invalid limit: must be between {_LIMIT_MIN} and {_LIMIT_MAX} (got {limit})"),
        )
    decoded_cursor = decode_cursor_or_400(cursor)
    parsed_user_id = _parse_user_id_or_400(user_id)

    page = await AuditLogService(session, ctx).list_page(
        cursor=decoded_cursor,
        action=action,
        resource_type=resource_type,
        user_id=parsed_user_id,
        from_ts=from_,
        to_ts=to,
        limit=limit,
    )
    return AuditLogsResponse(
        items=page.items,
        next_cursor=encode_next(page.next_cursor),
    )


def _parse_user_id_or_400(raw: str | None) -> uuid.UUID | None:
    """Validate ``?user_id`` is a UUID, returning 400 on a malformed value."""
    if raw is None:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid user_id: must be a UUID (got {raw!r})",
        ) from exc
