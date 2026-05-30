"""Suite read + write endpoints (docs/API.md §3.4) — scoped via project -> ws.

A suite has no ``workspace_id``; scope is enforced by checking the parent
project belongs to the active workspace. Each ``SuitePublic`` carries a
computed ``case_count`` (non-deleted cases), batched via one grouped query.

Write surface (M1d-4) covers ``POST /suites``, ``PATCH /suites/:id`` (incl.
optional ``case_order`` reorder), ``DELETE /suites/:id?confirmCascade=...``,
and ``POST /suites/:id/restore``. All write endpoints are gated by
``Role.QA / ADMIN / OWNER`` per docs/API.md role gate — VIEWER reads but
never mutates. ``case_order`` validation surfaces as a 400 with
``details.missing`` / ``details.unknown`` / ``details.duplicate``; missing
``confirmCascade`` against a populated suite surfaces as a 409
``CONFIRM_CASCADE_REQUIRED`` with ``childCount`` + ``resourceType``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_shared.domain.enums import Role

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.schemas.project import SuitePublic
from suitest_api.schemas.suite import SuiteCreate, SuiteUpdate
from suitest_api.services.suite_service import (
    CaseOrderMismatchError,
    ConfirmCascadeRequiredError,
    SuiteService,
)
from suitest_api.ws.publisher import publish_event

router = APIRouter(prefix="/api/v1", tags=["suites"])

# Role gate shared by every mutating endpoint per docs/API.md.
_WRITER_ROLES: set[Role] = {Role.QA, Role.ADMIN, Role.OWNER}
_writer_dep = require_role(_WRITER_ROLES)


async def _project_in_scope(repo: ProjectRepo, project_id: str, workspace_id: str) -> bool:
    project = await repo.get_by_id(project_id)
    return project is not None and project.workspace_id == workspace_id


def _build_service(session: AsyncSession, ctx: TenantContext) -> SuiteService:
    return SuiteService(ctx, SuiteRepo(session), ProjectRepo(session))


def _error_envelope(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    """Canonical ``{"error": {...}}`` payload per docs/API.md §3."""
    return {"error": {"code": code, "message": message, "details": details}}


async def _suite_public(
    suite_repo: SuiteRepo,
    *,
    suite_id: str,
    project_id: str,
    name: str,
    description: str | None,
    order: int,
    created_at: datetime,
    updated_at: datetime,
) -> SuitePublic:
    """Build a :class:`SuitePublic` with its (refreshed) ``case_count``."""
    counts = await suite_repo.case_counts([suite_id])
    return SuitePublic(
        id=suite_id,
        project_id=project_id,
        name=name,
        description=description,
        order=order,
        case_count=counts.get(suite_id, 0),
        created_at=created_at,
        updated_at=updated_at,
    )


@router.get("/suites", response_model=list[SuitePublic])
async def list_suites(
    project_id: str = Query(alias="projectId"),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[SuitePublic]:
    """List active (non-deleted) suites for a project; 404 cross-workspace."""
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


# ---------------------------------------------------------------------------
# M1d-4 write endpoints
# ---------------------------------------------------------------------------


def _raise_case_order_mismatch(exc: CaseOrderMismatchError) -> None:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_error_envelope(
            "INVALID_CASE_ORDER",
            "case_order must contain every active case id in the suite exactly once.",
            {
                "missing": exc.missing,
                "unknown": exc.unknown,
                "duplicate": exc.duplicates,
            },
        ),
    )


def _raise_confirm_cascade_required(exc: ConfirmCascadeRequiredError) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=_error_envelope(
            "CONFIRM_CASCADE_REQUIRED",
            "Suite has child cases — re-issue with confirmCascade=true to soft-delete both.",
            {
                "childCount": exc.child_count,
                "resourceType": "suite",
            },
        ),
    )


@router.post(
    "/suites",
    response_model=SuitePublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_suite(
    body: SuiteCreate,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> SuitePublic:
    """Create a suite under an in-scope project (QA+ only)."""
    svc = _build_service(session, ctx)
    outcome = await svc.create(body)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    await session.commit()
    suite_repo = SuiteRepo(session)
    public = await _suite_public(
        suite_repo,
        suite_id=outcome.suite.id,
        project_id=outcome.suite.project_id,
        name=outcome.suite.name,
        description=outcome.suite.description,
        order=outcome.suite.order,
        created_at=outcome.suite.created_at,
        updated_at=outcome.suite.updated_at,
    )
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return public


@router.patch("/suites/{suite_id}", response_model=SuitePublic)
async def update_suite(
    suite_id: str,
    body: SuiteUpdate,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> SuitePublic:
    """Patch metadata + optional atomic ``case_order`` reorder (QA+ only)."""
    svc = _build_service(session, ctx)
    try:
        outcome = await svc.update(suite_id, body)
    except CaseOrderMismatchError as exc:
        await session.rollback()
        _raise_case_order_mismatch(exc)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="suite not found")
    await session.commit()
    suite_repo = SuiteRepo(session)
    public = await _suite_public(
        suite_repo,
        suite_id=outcome.suite.id,
        project_id=outcome.suite.project_id,
        name=outcome.suite.name,
        description=outcome.suite.description,
        order=outcome.suite.order,
        created_at=outcome.suite.created_at,
        updated_at=outcome.suite.updated_at,
    )
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return public


@router.delete("/suites/{suite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_suite(
    suite_id: str,
    request: Request,
    confirm_cascade: bool = Query(default=False, alias="confirmCascade"),
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    """Soft-delete the suite + cascade child cases (with ``confirmCascade=true``).

    Returns 204 on success. Without ``confirmCascade=true`` against a suite
    that has at least one active child case, returns 409
    ``CONFIRM_CASCADE_REQUIRED`` with ``childCount`` + ``resourceType``.
    """
    svc = _build_service(session, ctx)
    try:
        outcome = await svc.soft_delete_with_cascade(suite_id, confirm_cascade=confirm_cascade)
    except ConfirmCascadeRequiredError as exc:
        await session.rollback()
        _raise_confirm_cascade_required(exc)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="suite not found")
    await session.commit()
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/suites/{suite_id}/restore", status_code=status.HTTP_204_NO_CONTENT)
async def restore_suite(
    suite_id: str,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    """Revive a soft-deleted suite (idempotent; children stay tombstoned).

    Re-POST after a successful restore returns the same 204 (per
    docs/API.md §328). Does not auto-restore child cases — restore each
    individually via ``POST /test-cases/:id/restore``.
    """
    svc = _build_service(session, ctx)
    outcome = await svc.restore(suite_id)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="suite not found")
    await session.commit()
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
