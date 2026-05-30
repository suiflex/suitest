"""Requirement + traceability read + write endpoints (docs/API.md §3.7).

Read paths (M1a/M1b) — ``GET /requirements``, ``GET /requirements/:id``,
``GET /traceability/matrix`` — stay workspace-scoped via the project. The matrix
is built from a handful of batched repo calls (requirements + project cases +
project defects + all links) and assembled in-process — no per-row N+1.

Write paths (M1d-6) — ``POST/PATCH/DELETE /requirements``, ``POST /requirements/:id/restore``,
``POST/DELETE /requirements/:id/links/...`` — require ``QA / ADMIN / OWNER`` per
docs/API.md role gate. Cross-workspace ``test_case_id`` on a link returns 400
``CROSS_WORKSPACE_LINK`` (NEVER 404 / 403) so the workspace-membership oracle
stays consistent with the rest of the API. Idempotent POST link returns the
existing join row.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.defects import DefectRepo
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.requirements import RequirementRepo
from suitest_db.repositories.test_cases import TestCaseRepo
from suitest_shared.domain.enums import Role
from suitest_shared.schemas.pagination import Page, PageMeta

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.routers._pagination import decode_cursor_or_400, encode_next
from suitest_api.schemas.requirement import (
    MatrixCase,
    MatrixDefect,
    MatrixRequirement,
    RequirementCreate,
    RequirementDetail,
    RequirementLinkCreate,
    RequirementListItem,
    RequirementUpdate,
    TraceabilityMatrix,
)
from suitest_api.services.requirement_write_service import (
    CrossWorkspaceLinkError,
    RequirementWriteService,
)
from suitest_api.ws.publisher import publish_event

requirements_router = APIRouter(prefix="/api/v1", tags=["requirements"])
traceability_router = APIRouter(prefix="/api/v1", tags=["traceability"])

# Per docs/API.md §3.7 — writes are QA+ (VIEWER reads freely but never mutates).
_WRITER_ROLES: set[Role] = {Role.QA, Role.ADMIN, Role.OWNER}
_writer_dep = require_role(_WRITER_ROLES)


def _build_write_service(session: AsyncSession, ctx: TenantContext) -> RequirementWriteService:
    """Compose a :class:`RequirementWriteService` from a session + tenant context."""
    return RequirementWriteService(
        ctx,
        RequirementRepo(session),
        ProjectRepo(session),
        TestCaseRepo(session),
    )


def _error_envelope(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    """Canonical ``{"error": {...}}`` payload per docs/API.md §3."""
    return {"error": {"code": code, "message": message, "details": details}}


async def _detail_from_id(session: AsyncSession, requirement_id: str) -> RequirementDetail | None:
    """Re-load + render a requirement as :class:`RequirementDetail`."""
    repo = RequirementRepo(session)
    req = await repo.get_by_id(requirement_id)
    if req is None:
        return None
    return RequirementDetail(
        id=req.id,
        project_id=req.project_id,
        public_id=req.public_id,
        title=req.title,
        description=req.description,
        source=req.source,
        external_url=req.external_url,
        case_public_ids=await repo.linked_case_public_ids(req.id),
        defect_public_ids=await repo.linked_defect_public_ids(req.id),
        created_at=req.created_at,
        updated_at=req.updated_at,
    )


async def _project_in_scope(session: AsyncSession, project_id: str, workspace_id: str) -> bool:
    project = await ProjectRepo(session).get_by_id(project_id)
    return project is not None and project.workspace_id == workspace_id


@requirements_router.get("/requirements", response_model=Page[RequirementListItem])
async def list_requirements(
    project_id: str = Query(alias="projectId"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> Page[RequirementListItem]:
    """List a project's requirements with link counts; 404 when cross-workspace."""
    if not await _project_in_scope(session, project_id, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    repo = RequirementRepo(session)
    decoded = decode_cursor_or_400(cursor)
    rows, next_keyset = await repo.list_by_project_paginated(
        project_id, cursor=decoded, limit=limit
    )
    counts = await repo.link_counts([r.id for r in rows])
    return Page[RequirementListItem](
        items=[
            RequirementListItem(
                id=r.id,
                project_id=r.project_id,
                public_id=r.public_id,
                title=r.title,
                description=r.description,
                source=r.source,
                external_url=r.external_url,
                link_count=counts.get(r.id, 0),
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ],
        meta=PageMeta(next_cursor=encode_next(next_keyset), limit=limit),
    )


@requirements_router.get("/requirements/{requirement_id}", response_model=RequirementDetail)
async def get_requirement(
    requirement_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> RequirementDetail:
    """Return a requirement with linked case + defect public ids; 404 if cross-ws.

    Soft-deleted requirements are invisible (404) to keep the public id namespace
    consistent with the LIST endpoint. Use ``POST /restore`` to bring them back.
    """
    repo = RequirementRepo(session)
    req = await repo.get_by_id(requirement_id)
    if (
        req is None
        or req.deleted_at is not None
        or not await _project_in_scope(session, req.project_id, ctx.workspace_id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="requirement not found")
    return RequirementDetail(
        id=req.id,
        project_id=req.project_id,
        public_id=req.public_id,
        title=req.title,
        description=req.description,
        source=req.source,
        external_url=req.external_url,
        case_public_ids=await repo.linked_case_public_ids(req.id),
        defect_public_ids=await repo.linked_defect_public_ids(req.id),
        created_at=req.created_at,
        updated_at=req.updated_at,
    )


# ---------------------------------------------------------------------------
# M1d-6 write endpoints
# ---------------------------------------------------------------------------


@requirements_router.post(
    "/requirements",
    response_model=RequirementDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_requirement(
    body: RequirementCreate,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> RequirementDetail:
    """Create a requirement under ``project_id``; ``REQ-N`` public id is assigned by listener."""
    svc = _build_write_service(session, ctx)
    outcome = await svc.create(body)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    await session.commit()
    detail = await _detail_from_id(session, outcome.requirement.id)
    if detail is None:  # pragma: no cover — race with concurrent delete
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="requirement missing"
        )
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return detail


@requirements_router.patch(
    "/requirements/{requirement_id}",
    response_model=RequirementDetail,
)
async def update_requirement(
    requirement_id: str,
    body: RequirementUpdate,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> RequirementDetail:
    """Patch metadata; only present fields are applied (``exclude_unset=True``)."""
    svc = _build_write_service(session, ctx)
    outcome = await svc.update(requirement_id, body)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="requirement not found")
    await session.commit()
    detail = await _detail_from_id(session, outcome.requirement.id)
    if detail is None:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="requirement missing"
        )
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return detail


@requirements_router.delete(
    "/requirements/{requirement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_requirement(
    requirement_id: str,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Soft-delete; subsequent re-delete returns 404 (the row is already hidden)."""
    svc = _build_write_service(session, ctx)
    outcome = await svc.soft_delete(requirement_id)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="requirement not found")
    await session.commit()
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )


@requirements_router.post(
    "/requirements/{requirement_id}/restore",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def restore_requirement(
    requirement_id: str,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Clear the ``deleted_at`` tombstone. Idempotent on already-active rows."""
    svc = _build_write_service(session, ctx)
    outcome = await svc.restore(requirement_id)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="requirement not found")
    await session.commit()
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )


@requirements_router.post(
    "/requirements/{requirement_id}/links",
    status_code=status.HTTP_201_CREATED,
)
async def create_requirement_link(
    requirement_id: str,
    body: RequirementLinkCreate,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, str]:
    """Link a requirement to a test case. Same workspace required.

    Cross-workspace ``test_case_id`` → 400 ``CROSS_WORKSPACE_LINK`` (both ws ids
    in ``details``). Idempotent: re-POSTing an existing pair returns ``201`` with
    the existing link id (no extra audit / WS row).
    """
    svc = _build_write_service(session, ctx)
    try:
        outcome = await svc.create_link(requirement_id, body.test_case_id)
    except CrossWorkspaceLinkError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_error_envelope(
                "CROSS_WORKSPACE_LINK",
                "Requirement and case belong to different workspaces.",
                {
                    "requirementId": exc.requirement_id,
                    "caseId": exc.case_id,
                    "requirementWorkspaceId": exc.requirement_workspace_id,
                    "caseWorkspaceId": exc.case_workspace_id,
                },
            ),
        ) from exc
    if outcome is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="requirement or case not found"
        )
    await session.commit()
    # Only publish a WS event when we actually inserted a row (skip idempotent path).
    if not outcome.ws_payload.get("idempotent"):
        await publish_event(
            request,
            topic=f"workspace:{ctx.workspace_id}",
            event=outcome.ws_event,
            data=outcome.ws_payload,
        )
    return {
        "id": outcome.link.id,
        "requirement_id": outcome.link.requirement_id,
        "case_id": outcome.link.case_id,
    }


@requirements_router.delete(
    "/requirements/{requirement_id}/links/{case_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_requirement_link(
    requirement_id: str,
    case_id: str,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Remove a link. 404 when the requirement is out-of-scope OR the link is gone."""
    svc = _build_write_service(session, ctx)
    outcome = await svc.delete_link(requirement_id, case_id)
    if outcome is None or outcome is False:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="link not found")
    await session.commit()
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event="requirement.link.deleted",
        data={"requirementId": requirement_id, "caseId": case_id},
    )


@traceability_router.get("/traceability/matrix", response_model=TraceabilityMatrix)
async def traceability_matrix(
    project_id: str = Query(alias="projectId"),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> TraceabilityMatrix:
    """Full traceability grid for a project (docs/API.md §3.7); 404 if cross-ws."""
    if not await _project_in_scope(session, project_id, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")

    req_repo = RequirementRepo(session)
    requirements = await req_repo.list_by_project(project_id)
    cases = await TestCaseRepo(session).list_by_project(project_id)
    defects = await DefectRepo(session).list_by_requirement_project(project_id)
    links = await req_repo.links_by_project(project_id)

    # id -> public_id lookups for cases; requirement -> [case public ids] from links.
    case_public_by_id = {c.id: c.public_id for c in cases}
    tests_by_req: dict[str, list[str]] = {r.id: [] for r in requirements}
    for link in links:
        public = case_public_by_id.get(link.case_id)
        if public is not None:
            tests_by_req.setdefault(link.requirement_id, []).append(public)
    defects_by_req: dict[str, list[str]] = {r.id: [] for r in requirements}
    for d in defects:
        if d.requirement_id is not None:
            defects_by_req.setdefault(d.requirement_id, []).append(d.public_id)

    return TraceabilityMatrix(
        requirements=[
            MatrixRequirement(
                id=r.public_id,
                title=r.title,
                tests=sorted(tests_by_req.get(r.id, [])),
                defects=sorted(defects_by_req.get(r.id, [])),
            )
            for r in requirements
        ],
        cases=[
            MatrixCase(id=c.public_id, name=c.name, source=c.source, status=c.status) for c in cases
        ],
        defects=[
            MatrixDefect(id=d.public_id, title=d.title, severity=d.severity, status=d.status)
            for d in defects
        ],
    )
