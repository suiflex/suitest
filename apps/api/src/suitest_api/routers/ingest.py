"""Lifecycle ingest endpoints (Phase 2, Approach A).

The ``suitest test`` lifecycle publishes generated cases and *completed* run
results here so the web app can render them. These are additive, tenant-scoped,
audit-logged writes — they never enqueue ARQ (the lifecycle already executed).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.audit import write_audit

from suitest_api.auth.db import get_async_session
from suitest_api.deps.api_key import tenant_via_api_key_or_session
from suitest_api.deps.scope import TenantContext
from suitest_api.schemas.ingest import (
    BulkImportBody,
    BulkImportResult,
    ResolveProjectBody,
    ResolveProjectResult,
    RunIngestBody,
    RunIngestResult,
)
from suitest_api.services.ingest_service import (
    ProjectNotFoundError,
    bulk_import_cases,
    ingest_run,
    resolve_project,
)

router = APIRouter(prefix="/api/v1", tags=["ingest"])


@router.post(
    "/ingest/resolve-project",
    response_model=ResolveProjectResult,
    status_code=status.HTTP_200_OK,
)
async def resolve_project_binding(
    body: ResolveProjectBody,
    ctx: TenantContext = Depends(tenant_via_api_key_or_session),
    session: AsyncSession = Depends(get_async_session),
) -> ResolveProjectResult:
    """Validate/repair a publisher's project binding (read-only, never creates)."""
    return await resolve_project(session, workspace_id=ctx.workspace_id, body=body)


@router.post(
    "/test-cases/bulk-import",
    response_model=BulkImportResult,
    status_code=status.HTTP_200_OK,
)
async def bulk_import(
    body: BulkImportBody,
    ctx: TenantContext = Depends(tenant_via_api_key_or_session),
    session: AsyncSession = Depends(get_async_session),
) -> BulkImportResult:
    """Upsert a suite's cases + steps from a lifecycle payload (idempotent by sourceRef)."""
    try:
        result = await bulk_import_cases(session, workspace_id=ctx.workspace_id, body=body)
    except ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await write_audit(
        session,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        action="lifecycle.bulk_import",
        resource_type="suite",
        resource_id=result.suite_id,
        metadata={"imported": len(result.imported)},
    )
    await session.commit()
    return result


@router.post(
    "/runs/ingest",
    response_model=RunIngestResult,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_completed_run(
    body: RunIngestBody,
    ctx: TenantContext = Depends(tenant_via_api_key_or_session),
    session: AsyncSession = Depends(get_async_session),
) -> RunIngestResult:
    """Record an already-completed run (run + run_steps + artifacts). No ARQ enqueue."""
    try:
        result = await ingest_run(session, workspace_id=ctx.workspace_id, body=body)
    except ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await write_audit(
        session,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        action="lifecycle.run_ingest",
        resource_type="run",
        resource_id=result.run_id,
        metadata={"status": result.status, "total": result.total},
    )
    await session.commit()
    return result
