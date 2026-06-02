"""Workspace read + M1d-28 settings/members/danger-zone endpoints (docs/API.md §3.1).

``GET /workspaces`` is user-scoped (lists only the caller's workspaces). The
detail + members routes verify membership inline and return **403** for a
non-member (the workspace exists but is not visible to the caller).

M1d-28 write surface — :func:`update_workspace`, :func:`invite_workspace_member`,
:func:`change_workspace_member_role`, :func:`remove_workspace_member`,
:func:`delete_workspace` — all share the same workspace-id path param. They
resolve membership + role inline against the request user (because the path
key is ``workspace_id`` not ``workspaceId``, so the generic ``TenantContext``
dep can't pick it up without a path-name detour).

The ``DELETE /workspaces/:id`` handler enqueues a placeholder
``workspace_cleanup`` ARQ job; the runner-side executor is a stub today (see
``apps/runner/.../jobs/workspace_cleanup.py``) and lands in M2+. The workspace
row is tombstoned via ``deleted_at`` so list/detail reads short-circuit even
while the cleanup is still queued.
"""

from __future__ import annotations

import uuid
from typing import Any

from arq.connections import ArqRedis
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.user import User
from suitest_db.repositories.workspace_members import WorkspaceMembershipRepo
from suitest_db.repositories.workspaces import WorkspaceRepo
from suitest_shared.domain.enums import Role

from suitest_api.auth.db import get_async_session
from suitest_api.auth.manager import current_active_user
from suitest_api.deps.arq import get_arq
from suitest_api.deps.scope import TenantContext
from suitest_api.schemas.workspace import (
    WorkspaceDeleteAccepted,
    WorkspaceDeleteConfirm,
    WorkspaceDetail,
    WorkspaceExportAccepted,
    WorkspaceExportStatus,
    WorkspaceMemberInvite,
    WorkspaceMemberPublic,
    WorkspaceMemberRoleUpdate,
    WorkspacePublic,
    WorkspaceUpdate,
)
from suitest_api.services.workspace_service import (
    ConfirmSlugMismatchError,
    MemberAlreadyExistsError,
    OwnerGrantRequiresOwnerError,
    SoleOwnerProtectedError,
    WorkspaceService,
    WorkspaceServiceError,
)
from suitest_api.ws.publisher import publish_event

router = APIRouter(prefix="/api/v1", tags=["workspaces"])

# ``workspace_cleanup`` ships as an additional ARQ function on the shared
# ``suitest:runs`` queue (single worker process today; see
# ``apps/runner/.../worker.py`` ``WorkerSettings.functions``). A future split
# into a dedicated low-priority queue is gated on the cleanup executor TODO.
_CLEANUP_QUEUE = "suitest:runs"


def _error_envelope(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    """Canonical ``{"error": {...}}`` payload per docs/API.md §3."""
    return {"error": {"code": code, "message": message, "details": details}}


async def _membership_or_403(repo: WorkspaceRepo, *, workspace_id: str, user: User) -> None:
    """Raise 403 unless ``user`` is a member of ``workspace_id``."""
    memberships = await repo.list_memberships_for_user(user.id)
    if not any(m.workspace_id == workspace_id for m in memberships):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user is not a member of the requested workspace",
        )


async def _resolve_role(
    member_repo: WorkspaceMembershipRepo, *, workspace_id: str, user: User
) -> Role:
    """Return the caller's role in ``workspace_id`` or raise 403."""
    membership = await member_repo.get(workspace_id, user.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user is not a member of the requested workspace",
        )
    return membership.role


def _build_service(
    session: AsyncSession, *, workspace_id: str, user_id: str, role: Role
) -> WorkspaceService:
    ctx = TenantContext(workspace_id=workspace_id, user_id=user_id, role=role)
    repo = WorkspaceRepo(session)
    member_repo = WorkspaceMembershipRepo(session)
    return WorkspaceService(ctx, repo, member_repo)


def _detail_from(ws: object) -> WorkspaceDetail:
    """Validate the ORM row + lift the in-JSON description back into the response."""
    detail = WorkspaceDetail.model_validate(ws)
    overrides = detail.mcp_routing_overrides or {}
    meta = overrides.get("_meta")
    if isinstance(meta, dict):
        description = meta.get("description")
        if isinstance(description, str):
            detail = detail.model_copy(update={"description": description})
    return detail


@router.get("/workspaces", response_model=list[WorkspacePublic])
async def list_workspaces(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[WorkspacePublic]:
    """List the workspaces the current user is a member of (active only)."""
    rows = await WorkspaceRepo(session).list_for_user(user.id)
    return [WorkspacePublic.model_validate(r) for r in rows]


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceDetail)
async def get_workspace(
    workspace_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> WorkspaceDetail:
    """Return one workspace; 403 when the caller is not a member."""
    repo = WorkspaceRepo(session)
    await _membership_or_403(repo, workspace_id=workspace_id, user=user)
    row = await repo.get_by_id(workspace_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace not found")
    return _detail_from(row)


@router.get("/workspaces/{workspace_id}/members", response_model=list[WorkspaceMemberPublic])
async def list_workspace_members(
    workspace_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[WorkspaceMemberPublic]:
    """List all members of a workspace; 403 when the caller is not a member."""
    repo = WorkspaceRepo(session)
    await _membership_or_403(repo, workspace_id=workspace_id, user=user)
    members = await repo.list_members(workspace_id)
    return [
        WorkspaceMemberPublic(
            user_id=m.user.id,
            email=m.user.email,
            name=m.user.name,
            role=m.role,
            joined_at=m.created_at,
        )
        for m in members
    ]


# ---------------------------------------------------------------------------
# M1d-28 write endpoints
# ---------------------------------------------------------------------------


def _raise_service_error(exc: WorkspaceServiceError, *, status_code: int) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=_error_envelope(exc.code, exc.message, exc.details),
    )


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceDetail)
async def update_workspace(
    workspace_id: str,
    request: Request,
    raw_body: dict[str, Any] = Body(default_factory=dict),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> WorkspaceDetail:
    """Patch General-tab fields. ADMIN+ required; ``slug`` is immutable."""
    if "slug" in raw_body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_error_envelope(
                "IMMUTABLE_SLUG",
                "workspace slug cannot be changed",
                {"workspaceId": workspace_id},
            ),
        )
    try:
        body = WorkspaceUpdate.model_validate(raw_body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_error_envelope(
                "VALIDATION_ERROR", "invalid request body", {"errors": exc.errors()}
            ),
        ) from exc

    member_repo = WorkspaceMembershipRepo(session)
    role = await _resolve_role(member_repo, workspace_id=workspace_id, user=user)
    svc = _build_service(session, workspace_id=workspace_id, user_id=str(user.id), role=role)
    try:
        outcome = await svc.update_settings(
            workspace_id,
            name=body.name,
            description=body.description,
            strict_zero_validation=body.strict_zero_validation,
            mcp_routing_overrides=body.mcp_routing_overrides,
        )
    except WorkspaceServiceError as exc:
        await session.rollback()
        _raise_service_error(exc, status_code=status.HTTP_403_FORBIDDEN)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace not found")
    await session.commit()
    await session.refresh(outcome.workspace)
    detail = _detail_from(outcome.workspace)
    if body.description is not None:
        detail = detail.model_copy(update={"description": body.description})
    await publish_event(
        request,
        topic=f"workspace:{workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return detail


@router.post(
    "/workspaces/{workspace_id}/members",
    response_model=WorkspaceMemberPublic,
    status_code=status.HTTP_201_CREATED,
)
async def invite_workspace_member(
    workspace_id: str,
    body: WorkspaceMemberInvite,
    request: Request,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> WorkspaceMemberPublic:
    """Add a member by email + role. OWNER/ADMIN required; OWNER grant is OWNER-only."""
    member_repo = WorkspaceMembershipRepo(session)
    role = await _resolve_role(member_repo, workspace_id=workspace_id, user=user)
    svc = _build_service(session, workspace_id=workspace_id, user_id=str(user.id), role=role)
    try:
        outcome = await svc.invite_member(workspace_id, email=body.email, role=body.role)
    except OwnerGrantRequiresOwnerError as exc:
        await session.rollback()
        _raise_service_error(exc, status_code=status.HTTP_403_FORBIDDEN)
    except MemberAlreadyExistsError as exc:
        await session.rollback()
        _raise_service_error(exc, status_code=status.HTTP_409_CONFLICT)
    except WorkspaceServiceError as exc:
        await session.rollback()
        _raise_service_error(exc, status_code=status.HTTP_403_FORBIDDEN)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace not found")
    await session.commit()
    # Reload the membership row so we can return the canonical joined_at + name
    # (the placeholder-user path mints a fresh row that the service helper has
    # already refreshed; loading here keeps the response shape uniform).
    reloaded = await member_repo.get(workspace_id, outcome.member_id)
    if reloaded is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="membership missing"
        )
    await publish_event(
        request,
        topic=f"workspace:{workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return WorkspaceMemberPublic(
        user_id=reloaded.user.id,
        email=reloaded.user.email,
        name=reloaded.user.name,
        role=reloaded.role,
        joined_at=reloaded.created_at,
    )


@router.patch(
    "/workspaces/{workspace_id}/members/{user_id}",
    response_model=WorkspaceMemberPublic,
)
async def change_workspace_member_role(
    workspace_id: str,
    user_id: uuid.UUID,
    body: WorkspaceMemberRoleUpdate,
    request: Request,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> WorkspaceMemberPublic:
    """Change one member's role. OWNER/ADMIN required; OWNER grant is OWNER-only."""
    member_repo = WorkspaceMembershipRepo(session)
    role = await _resolve_role(member_repo, workspace_id=workspace_id, user=user)
    svc = _build_service(session, workspace_id=workspace_id, user_id=str(user.id), role=role)
    try:
        outcome = await svc.change_member_role(workspace_id, user_id, role=body.role)
    except OwnerGrantRequiresOwnerError as exc:
        await session.rollback()
        _raise_service_error(exc, status_code=status.HTTP_403_FORBIDDEN)
    except SoleOwnerProtectedError as exc:
        await session.rollback()
        _raise_service_error(exc, status_code=status.HTTP_400_BAD_REQUEST)
    except WorkspaceServiceError as exc:
        await session.rollback()
        _raise_service_error(exc, status_code=status.HTTP_403_FORBIDDEN)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    await session.commit()
    reloaded = await member_repo.get(workspace_id, user_id)
    if reloaded is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="membership missing"
        )
    await publish_event(
        request,
        topic=f"workspace:{workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return WorkspaceMemberPublic(
        user_id=reloaded.user.id,
        email=reloaded.user.email,
        name=reloaded.user.name,
        role=reloaded.role,
        joined_at=reloaded.created_at,
    )


@router.delete(
    "/workspaces/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_workspace_member(
    workspace_id: str,
    user_id: uuid.UUID,
    request: Request,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    """Remove a member. Self-removal is allowed except for the sole OWNER."""
    member_repo = WorkspaceMembershipRepo(session)
    role = await _resolve_role(member_repo, workspace_id=workspace_id, user=user)
    svc = _build_service(session, workspace_id=workspace_id, user_id=str(user.id), role=role)
    try:
        outcome = await svc.remove_member(workspace_id, user_id)
    except SoleOwnerProtectedError as exc:
        await session.rollback()
        _raise_service_error(exc, status_code=status.HTTP_400_BAD_REQUEST)
    except WorkspaceServiceError as exc:
        await session.rollback()
        _raise_service_error(exc, status_code=status.HTTP_403_FORBIDDEN)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    await session.commit()
    await publish_event(
        request,
        topic=f"workspace:{workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/workspaces/{workspace_id}",
    response_model=WorkspaceDeleteAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def delete_workspace(
    workspace_id: str,
    body: WorkspaceDeleteConfirm,
    request: Request,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
    arq: ArqRedis = Depends(get_arq),
) -> WorkspaceDeleteAccepted:
    """OWNER-only slug-typed-confirm delete. Tombstones now, cleans up async."""
    member_repo = WorkspaceMembershipRepo(session)
    role = await _resolve_role(member_repo, workspace_id=workspace_id, user=user)
    svc = _build_service(session, workspace_id=workspace_id, user_id=str(user.id), role=role)
    try:
        outcome = await svc.initiate_delete(workspace_id, confirm_slug=body.confirm_slug)
    except ConfirmSlugMismatchError as exc:
        await session.rollback()
        _raise_service_error(exc, status_code=status.HTTP_400_BAD_REQUEST)
    except WorkspaceServiceError as exc:
        await session.rollback()
        _raise_service_error(exc, status_code=status.HTTP_403_FORBIDDEN)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace not found")

    job = await arq.enqueue_job("workspace_cleanup", workspace_id, _queue_name=_CLEANUP_QUEUE)
    cleanup_job_id = job.job_id if job is not None else f"local-{workspace_id}"
    await session.commit()
    await publish_event(
        request,
        topic=f"workspace:{workspace_id}",
        event=outcome.ws_event,
        data={**outcome.ws_payload, "cleanupJobId": cleanup_job_id},
    )
    return WorkspaceDeleteAccepted(cleanup_job_id=cleanup_job_id)


# M4-29 workspace export. OWNER/ADMIN only — the archive contains every entity
# (secrets REDACTED) so it must not be exportable by viewers/members.
_EXPORT_ROLES: set[Role] = {Role.OWNER, Role.ADMIN}
_EXPORT_QUEUE = "suitest:runs"


@router.post(
    "/workspaces/{workspace_id}/export",
    response_model=WorkspaceExportAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def export_workspace(
    workspace_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
    arq: ArqRedis = Depends(get_arq),
) -> WorkspaceExportAccepted:
    """Enqueue assembly of a portable workspace archive (M4-29). OWNER/ADMIN."""
    from suitest_db.ids import new_id

    member_repo = WorkspaceMembershipRepo(session)
    role = await _resolve_role(member_repo, workspace_id=workspace_id, user=user)
    if role not in _EXPORT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="workspace export requires OWNER or ADMIN",
        )
    export_id = new_id()
    job = await arq.enqueue_job(
        "export_workspace", workspace_id, export_id, _queue_name=_EXPORT_QUEUE
    )
    return WorkspaceExportAccepted(export_job_id=job.job_id if job is not None else export_id)


@router.get(
    "/workspaces/{workspace_id}/export/{job_id}",
    response_model=WorkspaceExportStatus,
)
async def get_workspace_export(
    workspace_id: str,
    job_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
    arq: ArqRedis = Depends(get_arq),
) -> WorkspaceExportStatus:
    """Poll an export job; surfaces the 24h presigned download URL when ready."""
    from arq.jobs import Job as ArqJob

    member_repo = WorkspaceMembershipRepo(session)
    role = await _resolve_role(member_repo, workspace_id=workspace_id, user=user)
    if role not in _EXPORT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="workspace export requires OWNER or ADMIN",
        )
    job = ArqJob(job_id, arq, _queue_name=_EXPORT_QUEUE)
    job_status = await job.status()
    if job_status in {"complete", "Complete"} or str(job_status) == "JobStatus.complete":
        result = await job.result(timeout=1)
        if isinstance(result, dict):
            return WorkspaceExportStatus(
                status=str(result.get("status", "error")),
                download_url=_opt_str(result.get("download_url")),
                size_bytes=_opt_int(result.get("size_bytes")),
                error=_opt_str(result.get("error")),
            )
        return WorkspaceExportStatus(status="error", error="malformed job result")
    if str(job_status) in {"JobStatus.not_found", "not_found"}:
        return WorkspaceExportStatus(status="not_found")
    return WorkspaceExportStatus(status="in_progress")


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _opt_int(value: object) -> int | None:
    return value if isinstance(value, int) else None
