"""Audit log read endpoint — Dashboard agent activity feed (docs/API.md §3.11).

Workspace-scoped, newest-first, bounded (limit ≤ 100). The ``action`` query is a
prefix filter — callers pass canonical glob form (``agent.*``) and the repository
strips the trailing wildcard before the ``LIKE`` lookup. M1a write path
(``AuditContextMiddleware`` + ``AuditLogRepo.append``) already populates the
table; this router exposes the read side.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.audit_logs import AuditLogRepo

from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership

router = APIRouter(prefix="/api/v1", tags=["audit"])


class AuditLogEntry(BaseModel):
    """One audit row exposed in the Dashboard agent activity feed."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    action: str
    resource_type: str = Field(alias="resourceType")
    resource_id: str = Field(alias="resourceId")
    user_id: str | None = Field(default=None, alias="userId")
    created_at: datetime = Field(alias="createdAt")


class AuditLogResponse(BaseModel):
    """``GET /audit-logs`` envelope — small bounded list, no cursor."""

    items: list[AuditLogEntry] = Field(default_factory=list)


@router.get("/audit-logs", response_model=AuditLogResponse)
async def list_audit_logs(
    action: str | None = Query(default=None, description="Action prefix filter (e.g. 'agent.*')"),
    limit: int = Query(default=20, ge=1, le=100),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> AuditLogResponse:
    """List audit log entries for the workspace, optionally filtered by action prefix."""
    rows = await AuditLogRepo(session).list_by_workspace_filtered(
        workspace_id=ctx.workspace_id,
        action_prefix=action,
        limit=limit,
    )
    return AuditLogResponse(
        items=[
            AuditLogEntry(
                id=r.id,
                action=r.action,
                resource_type=r.resource_type,
                resource_id=r.resource_id,
                user_id=str(r.user_id) if r.user_id is not None else None,
                created_at=r.created_at,
            )
            for r in rows
        ]
    )
