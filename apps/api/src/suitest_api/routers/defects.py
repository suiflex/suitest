"""Defect read + M1d-9 write endpoints (docs/API.md §3.6) — workspace-scoped directly.

Defects carry ``workspace_id``, so scoping is a direct column check. The timeline
is the defect's synthetic ``created`` event followed by its audit_log rows in
ascending time (built by ``DefectRepo.timeline``).

Write surface (M1d-9): ``POST /defects`` (manual file, ``SUIT-N`` public id),
``PATCH /defects/:id`` (status flow + assignee + severity), and
``POST /defects/:id/sync-external``. Mutations are gated by ``Role.QA / ADMIN /
OWNER`` per docs/API.md role table — VIEWER reads but never mutates. Status
transitions outside the matrix surface as 400
``INVALID_STATUS_TRANSITION``; sync-external surfaces as 501
``ADAPTER_NOT_REGISTERED`` until the adapter registry ships in M1d-11+.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.defects import DefectRepo
from suitest_shared.domain.enums import DefectStatus, Role, Severity
from suitest_shared.schemas.pagination import Page, PageMeta

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.routers._pagination import decode_cursor_or_400, encode_next
from suitest_api.schemas.defect import (
    DefectCreate,
    DefectDetail,
    DefectListItem,
    DefectTimelineEntry,
    DefectUpdate,
    ExternalIssuePublic,
)
from suitest_api.services.defect_service import (
    AdapterNotRegisteredError,
    DefectService,
    InvalidStatusTransitionError,
    LinkedResourceMissingError,
)
from suitest_api.ws.publisher import publish_event

router = APIRouter(prefix="/api/v1", tags=["defects"])


# Role gate shared by every mutating endpoint per docs/API.md role table.
_WRITER_ROLES: set[Role] = {Role.QA, Role.ADMIN, Role.OWNER}
_writer_dep = require_role(_WRITER_ROLES)


def _error_envelope(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    """Canonical ``{"error": {...}}`` payload per docs/API.md §3."""
    return {"error": {"code": code, "message": message, "details": details}}


def _build_detail(
    defect: Any,
    *,
    case_public: str | None,
    run_public: str | None,
    req_public: str | None,
    external: list[ExternalIssuePublic],
) -> DefectDetail:
    """Assemble the canonical detail payload from the ORM row + resolved links."""
    return DefectDetail(
        id=defect.id,
        public_id=defect.public_id,
        workspace_id=defect.workspace_id,
        title=defect.title,
        description=defect.description,
        severity=defect.severity,
        status=defect.status,
        component=defect.component,
        assignee_id=defect.assignee_id,
        agent_diagnosis_kind=defect.agent_diagnosis_kind,
        created_by=defect.created_by,
        created_at=defect.created_at,
        updated_at=defect.updated_at,
        resolved_at=defect.resolved_at,
        test_case_public_id=case_public,
        run_public_id=run_public,
        requirement_public_id=req_public,
        external_issues=external,
    )


async def _build_detail_from_id(
    session: AsyncSession, workspace_id: str, defect_id: str
) -> DefectDetail:
    """Re-load + materialise the detail DTO post-commit (router response)."""
    repo = DefectRepo(session)
    defect = await repo.get_by_id(defect_id)
    if defect is None or defect.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="defect missing"
        )
    case_public, run_public, req_public = await repo.resolve_link_public_ids(defect)
    external = await repo.get_external_issues(defect.id)
    return _build_detail(
        defect,
        case_public=case_public,
        run_public=run_public,
        req_public=req_public,
        external=[ExternalIssuePublic.model_validate(e) for e in external],
    )


@router.get("/defects", response_model=Page[DefectListItem])
async def list_defects(
    status_: DefectStatus | None = Query(default=None, alias="status"),
    severity: Severity | None = Query(default=None),
    assignee_id: uuid.UUID | None = Query(default=None, alias="assigneeId"),
    component: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> Page[DefectListItem]:
    """List the workspace's defects with filters, keyset-paginated."""
    decoded = decode_cursor_or_400(cursor)
    rows, next_keyset = await DefectRepo(session).list_by_workspace(
        ctx.workspace_id,
        status=status_,
        severity=severity,
        assignee_id=assignee_id,
        component=component,
        cursor=decoded,
        limit=limit,
    )
    return Page[DefectListItem](
        items=[DefectListItem.model_validate(r) for r in rows],
        meta=PageMeta(next_cursor=encode_next(next_keyset), limit=limit),
    )


@router.get("/defects/{defect_id}", response_model=DefectDetail)
async def get_defect(
    defect_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> DefectDetail:
    """Return a defect with linked public ids + external issues; 404 if cross-ws."""
    repo = DefectRepo(session)
    defect = await repo.get_by_id(defect_id)
    if defect is None or defect.workspace_id != ctx.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="defect not found")
    case_public, run_public, req_public = await repo.resolve_link_public_ids(defect)
    external = await repo.get_external_issues(defect.id)
    return _build_detail(
        defect,
        case_public=case_public,
        run_public=run_public,
        req_public=req_public,
        external=[ExternalIssuePublic.model_validate(e) for e in external],
    )


@router.get("/defects/{defect_id}/timeline", response_model=list[DefectTimelineEntry])
async def get_defect_timeline(
    defect_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[DefectTimelineEntry]:
    """Return the defect's creation event + audit rows in ascending time; 404 if cross-ws."""
    repo = DefectRepo(session)
    defect = await repo.get_by_id(defect_id)
    if defect is None or defect.workspace_id != ctx.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="defect not found")
    entries = await repo.timeline(defect_id)
    return [DefectTimelineEntry(at=e.at, action=e.action, actor_id=e.actor_id) for e in entries]


# ---------------------------------------------------------------------------
# M1d-9 write endpoints
# ---------------------------------------------------------------------------


def _raise_invalid_transition(exc: InvalidStatusTransitionError) -> None:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_error_envelope(
            "INVALID_STATUS_TRANSITION",
            (
                f"Defect status transition {exc.from_status.value} -> "
                f"{exc.to_status.value} is not allowed. Set 'force': true to override."
            ),
            {
                "from": exc.from_status.value,
                "to": exc.to_status.value,
            },
        ),
    )


def _raise_linked_missing(exc: LinkedResourceMissingError) -> None:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_error_envelope(
            "LINKED_RESOURCE_NOT_FOUND",
            f"Linked {exc.field} not found in workspace.",
            {"field": exc.field, "value": exc.value},
        ),
    )


def _raise_adapter_not_registered(exc: AdapterNotRegisteredError) -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=_error_envelope(
            "ADAPTER_NOT_REGISTERED",
            (
                "No external tracker adapter is registered for this workspace. "
                "Configure a Jira / Linear / GitHub integration first."
            ),
            {"defectId": exc.defect_id},
        ),
    )


@router.post(
    "/defects",
    response_model=DefectDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_defect(
    body: DefectCreate,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> DefectDetail:
    """Manually file a defect (``SUIT-N`` public id, ``created_by='user:<id>'``)."""
    svc = DefectService(ctx, DefectRepo(session))
    try:
        outcome = await svc.create(body)
    except LinkedResourceMissingError as exc:
        await session.rollback()
        _raise_linked_missing(exc)
    await session.commit()
    detail = await _build_detail_from_id(session, ctx.workspace_id, outcome.defect.id)
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return detail


@router.patch("/defects/{defect_id}", response_model=DefectDetail)
async def update_defect(
    defect_id: str,
    body: DefectUpdate,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> DefectDetail:
    """Patch status / severity / assignee / description; honours the transition matrix."""
    svc = DefectService(ctx, DefectRepo(session))
    try:
        outcome = await svc.update(defect_id, body)
    except InvalidStatusTransitionError as exc:
        await session.rollback()
        _raise_invalid_transition(exc)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="defect not found")
    await session.commit()
    detail = await _build_detail_from_id(session, ctx.workspace_id, outcome.defect.id)
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return detail


@router.post("/defects/{defect_id}/sync-external", response_model=DefectDetail)
async def sync_defect_external(
    defect_id: str,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> DefectDetail:
    """Force re-sync the defect to the configured external tracker.

    Returns 404 for cross-workspace ids before raising 501
    ``ADAPTER_NOT_REGISTERED`` — the adapter registry lands in M1d-11+ and
    will replace the unconditional 501 with real Jira / Linear dispatch.
    """
    svc = DefectService(ctx, DefectRepo(session))
    try:
        await svc.sync_external(defect_id)
    except AdapterNotRegisteredError as exc:
        _raise_adapter_not_registered(exc)
    # If we reach here ``sync_external`` returned ``None`` (cross-workspace) —
    # mirror the read-side 404 envelope rather than leaking existence.
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="defect not found")
