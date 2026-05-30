"""Project read + write endpoints (docs/API.md §3.2).

Read path: workspace-scoped, paginated, default-filters ``deleted_at IS NULL``.

Write surface (M1d-5) covers ``POST /projects``, ``PATCH /projects/:id``,
``DELETE /projects/:id?confirmCascade=...``, and ``POST /projects/:id/restore``.
All write endpoints are gated by ``Role.ADMIN / OWNER`` per ``docs/API.md
§3.2`` — QA and VIEWER read but never mutate projects. Cascade soft-delete
tombstones child suites + cases in a single transaction; restore only flips
the project tombstone.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.projects import ProjectRepo
from suitest_shared.domain.enums import Role
from suitest_shared.schemas.pagination import Page, PageMeta

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.routers._pagination import decode_cursor_or_400, encode_next
from suitest_api.schemas.project import (
    ProjectCreate,
    ProjectPublic,
    ProjectUpdate,
)
from suitest_api.services.project_service import (
    ConfirmCascadeRequiredError,
    ImmutableSlugError,
    InvalidGatingSuiteError,
    ProjectService,
    SlugConflictError,
)
from suitest_api.ws.publisher import publish_event

router = APIRouter(prefix="/api/v1", tags=["projects"])

# Role gate shared by every mutating endpoint per docs/API.md §3.2 — project
# CRUD is ADMIN/OWNER only (QA can author cases but not own projects).
_WRITER_ROLES: set[Role] = {Role.ADMIN, Role.OWNER}
_writer_dep = require_role(_WRITER_ROLES)


def _build_service(session: AsyncSession, ctx: TenantContext) -> ProjectService:
    return ProjectService(ctx, ProjectRepo(session))


def _error_envelope(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    """Canonical ``{"error": {...}}`` payload per docs/API.md §3."""
    return {"error": {"code": code, "message": message, "details": details}}


def _raise_slug_conflict(exc: SlugConflictError) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=_error_envelope(
            "DUPLICATE_PROJECT_SLUG",
            f"Project slug {exc.slug!r} is already in use in this workspace.",
            {"slug": exc.slug},
        ),
    )


def _raise_immutable_slug() -> None:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_error_envelope(
            "IMMUTABLE_SLUG",
            "Project slug is immutable; create a new project to rename it.",
            {"resourceType": "project"},
        ),
    )


def _raise_invalid_gating_suite(exc: InvalidGatingSuiteError) -> None:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_error_envelope(
            "INVALID_GATING_SUITE",
            "Gating suite must belong to the same project.",
            {"suiteId": exc.suite_id, "projectId": exc.project_id},
        ),
    )


def _raise_confirm_cascade_required(exc: ConfirmCascadeRequiredError) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=_error_envelope(
            "CONFIRM_CASCADE_REQUIRED",
            "Project has child suites — re-issue with confirmCascade=true to cascade.",
            {
                "suiteCount": exc.suite_count,
                "caseCount": exc.case_count,
                "resourceType": "project",
            },
        ),
    )


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


@router.get("/projects", response_model=Page[ProjectPublic])
async def list_projects(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> Page[ProjectPublic]:
    """List the current workspace's active projects, keyset-paginated."""
    decoded = decode_cursor_or_400(cursor)
    rows, next_keyset = await ProjectRepo(session).list_by_workspace_paginated(
        ctx.workspace_id, cursor=decoded, limit=limit
    )
    return Page[ProjectPublic](
        items=[ProjectPublic.model_validate(r) for r in rows],
        meta=PageMeta(next_cursor=encode_next(next_keyset), limit=limit),
    )


@router.get("/projects/{project_id}", response_model=ProjectPublic)
async def get_project(
    project_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> ProjectPublic:
    """Return one active project; 404 when cross-workspace or tombstoned."""
    row = await ProjectRepo(session).get_active_by_id(project_id)
    if row is None or row.workspace_id != ctx.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    return ProjectPublic.model_validate(row)


# ---------------------------------------------------------------------------
# M1d-5 write endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/projects",
    response_model=ProjectPublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    body: ProjectCreate,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> ProjectPublic:
    """Create a project under the active workspace (ADMIN/OWNER only)."""
    svc = _build_service(session, ctx)
    try:
        outcome = await svc.create(body)
    except SlugConflictError as exc:
        # service already rolled back; map to 409.
        _raise_slug_conflict(exc)
    await session.commit()
    project_row = await ProjectRepo(session).get_active_by_id(outcome.project.id)
    if project_row is None:  # pragma: no cover — flushed row must exist
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    public = ProjectPublic.model_validate(project_row)
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return public


@router.patch("/projects/{project_id}", response_model=ProjectPublic)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> ProjectPublic:
    """Patch metadata (ADMIN/OWNER only).

    Slug is immutable — PATCH with a ``slug`` field returns 400
    ``IMMUTABLE_SLUG``. ``gating_suite_id`` must belong to the target project,
    else 400 ``INVALID_GATING_SUITE``.
    """
    svc = _build_service(session, ctx)
    try:
        outcome = await svc.update(project_id, body)
    except ImmutableSlugError:
        await session.rollback()
        _raise_immutable_slug()
    except InvalidGatingSuiteError as exc:
        await session.rollback()
        _raise_invalid_gating_suite(exc)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    await session.commit()
    project_row = await ProjectRepo(session).get_active_by_id(outcome.project.id)
    if project_row is None:  # pragma: no cover — flushed row must exist
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    public = ProjectPublic.model_validate(project_row)
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return public


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    request: Request,
    confirm_cascade: bool = Query(default=False, alias="confirmCascade"),
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    """Soft-delete the project + cascade child suites + cases (with ``confirmCascade=true``).

    Returns 204 on success. Without ``confirmCascade=true`` against a project
    that has at least one active child suite, returns 409
    ``CONFIRM_CASCADE_REQUIRED`` with ``suiteCount`` / ``caseCount`` /
    ``resourceType``.
    """
    svc = _build_service(session, ctx)
    try:
        outcome = await svc.soft_delete_with_cascade(project_id, confirm_cascade=confirm_cascade)
    except ConfirmCascadeRequiredError as exc:
        await session.rollback()
        _raise_confirm_cascade_required(exc)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    await session.commit()
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/projects/{project_id}/restore", status_code=status.HTTP_204_NO_CONTENT)
async def restore_project(
    project_id: str,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    """Revive a soft-deleted project (idempotent; children stay tombstoned).

    Re-POST after a successful restore returns 204 (idempotent). Does NOT
    auto-restore child suites + cases — restore each individually via
    ``POST /suites/:id/restore`` / ``POST /test-cases/:id/restore``.
    """
    svc = _build_service(session, ctx)
    outcome = await svc.restore(project_id)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    await session.commit()
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
