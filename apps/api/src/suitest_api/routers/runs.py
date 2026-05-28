"""Run / run-step / log / artifact read endpoints (docs/API.md §3.5).

All scoped via project -> workspace. ``GET /runs/:id/logs`` concatenates each
RunStep's stdout + stderr in step_order into a flat line stream and paginates it
with a simple integer line-offset cursor (M1a; a richer per-chunk cursor lands
with live streaming in M3). Artifact download produces a presigned URL via
:func:`build_signed_url` (object store) or a placeholder for ``file://`` artifacts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.runs import RunRepo
from suitest_shared.domain.enums import RunStatus
from suitest_shared.schemas.pagination import Page, PageMeta

from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.routers._pagination import decode_cursor_or_400, encode_next
from suitest_api.schemas.run import (
    ArtifactPublic,
    ArtifactSignedUrl,
    RunDetail,
    RunListItem,
    RunLogPage,
    RunNetworkResponse,
    RunsSummary,
    RunStepPublic,
    RunSummary,
)
from suitest_api.services.artifact_signing import build_signed_url

router = APIRouter(prefix="/api/v1", tags=["runs"])

_LOG_PAGE_SIZE = 500  # log lines per page


async def _project_in_scope(session: AsyncSession, project_id: str, workspace_id: str) -> bool:
    project = await ProjectRepo(session).get_by_id(project_id)
    return project is not None and project.workspace_id == workspace_id


async def _run_in_scope_or_404(session: AsyncSession, run_id: str, workspace_id: str) -> None:
    run = await RunRepo(session).get_by_id(run_id)
    if run is None or not await _project_in_scope(session, run.project_id, workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")


@router.get("/runs", response_model=Page[RunListItem])
async def list_runs(
    project_id: str = Query(alias="projectId"),
    status_: RunStatus | None = Query(default=None, alias="status"),
    branch: str | None = Query(default=None),
    env: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> Page[RunListItem]:
    """List a project's runs with filters; 404 when the project is cross-workspace."""
    if not await _project_in_scope(session, project_id, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    decoded = decode_cursor_or_400(cursor)
    rows, next_keyset = await RunRepo(session).list_by_project(
        project_id, status=status_, branch=branch, env=env, cursor=decoded, limit=limit
    )
    return Page[RunListItem](
        items=[RunListItem.model_validate(r) for r in rows],
        meta=PageMeta(next_cursor=encode_next(next_keyset), limit=limit),
    )


@router.get("/runs/summary", response_model=RunsSummary)
async def get_runs_summary(
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> RunsSummary:
    """Aggregated counters for the Runs dashboard summary bar (docs/API.md §3.5).

    Counts are workspace-scoped (joined via ``projects``). ``failed`` folds
    ``FAIL`` + ``ERROR`` together to match the Runs UI's binary outcome card.
    Static endpoint declared BEFORE the dynamic ``/runs/{run_id}`` route below
    so FastAPI's path matcher doesn't try to treat ``summary`` as a run id.
    """
    counts = await RunRepo(session).summary_for_workspace(ctx.workspace_id)
    return RunsSummary(
        active=counts.get(RunStatus.RUNNING.value, 0),
        today=counts.get("today", 0),
        passed=counts.get(RunStatus.PASS.value, 0),
        failed=counts.get(RunStatus.FAIL.value, 0) + counts.get(RunStatus.ERROR.value, 0),
        avg_duration_ms=counts.get("avg_duration_ms", 0),
        queued=counts.get(RunStatus.QUEUED.value, 0),
    )


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> RunDetail:
    """Return a run with a step-outcome summary; 404 when cross-workspace."""
    repo = RunRepo(session)
    pair = await repo.get_with_summary(run_id)
    if pair is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    run, summary = pair
    if not await _project_in_scope(session, run.project_id, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return RunDetail(
        id=run.id,
        public_id=run.public_id,
        project_id=run.project_id,
        name=run.name,
        branch=run.branch,
        commit_sha=run.commit_sha,
        env=run.env,
        trigger=run.trigger,
        status=run.status,
        tier_at_runtime=run.tier_at_runtime,
        started_at=run.started_at,
        completed_at=run.completed_at,
        duration_ms=run.duration_ms,
        created_at=run.created_at,
        updated_at=run.updated_at,
        summary=RunSummary(
            total_steps=summary.total_steps,
            passed_steps=summary.passed_steps,
            failed_steps=summary.failed_steps,
            duration_ms=summary.duration_ms,
        ),
    )


@router.get("/runs/{run_id}/steps", response_model=list[RunStepPublic])
async def get_run_steps(
    run_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[RunStepPublic]:
    """Return a run's steps (ordered) with outcomes + case public ids; 404 if cross-ws."""
    await _run_in_scope_or_404(session, run_id, ctx.workspace_id)
    pairs = await RunRepo(session).get_steps_with_case_public_id(run_id)
    return [
        RunStepPublic(
            id=step.id,
            run_id=step.run_id,
            case_id=step.case_id,
            case_public_id=public_id,
            step_order=step.step_order,
            outcome=step.outcome,
            started_at=step.started_at,
            completed_at=step.completed_at,
            duration_ms=step.duration_ms,
            error_message=step.error_message,
        )
        for step, public_id in pairs
    ]


@router.get("/runs/{run_id}/logs", response_model=RunLogPage)
async def get_run_logs(
    run_id: str,
    cursor: str | None = Query(default=None),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> RunLogPage:
    """Concatenated stdout/stderr text in step_order, paginated by line offset."""
    await _run_in_scope_or_404(session, run_id, ctx.workspace_id)
    steps = await RunRepo(session).get_steps(run_id)
    lines: list[str] = []
    for step in steps:
        if step.stdout:
            lines.extend(step.stdout.splitlines())
        if step.stderr:
            lines.extend(step.stderr.splitlines())

    offset = _parse_offset_cursor(cursor)
    page = lines[offset : offset + _LOG_PAGE_SIZE]
    next_offset = offset + _LOG_PAGE_SIZE
    next_cursor = str(next_offset) if next_offset < len(lines) else None
    return RunLogPage(lines=page, next_cursor=next_cursor)


def _parse_offset_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = int(cursor)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid cursor"
        ) from exc
    if value < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid cursor")
    return value


@router.get("/runs/{run_id}/artifacts", response_model=list[ArtifactPublic])
async def get_run_artifacts(
    run_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[ArtifactPublic]:
    """List a run's artifacts; 404 when the run is cross-workspace."""
    await _run_in_scope_or_404(session, run_id, ctx.workspace_id)
    rows = await RunRepo(session).get_artifacts(run_id)
    return [ArtifactPublic.model_validate(r) for r in rows]


@router.get("/runs/{run_id}/artifacts/{artifact_id}", response_model=ArtifactSignedUrl)
async def get_artifact_signed_url(
    run_id: str,
    artifact_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> ArtifactSignedUrl:
    """Return a presigned download URL for one artifact; 404 if run/artifact unknown."""
    await _run_in_scope_or_404(session, run_id, ctx.workspace_id)
    repo = RunRepo(session)
    artifacts = await repo.get_artifacts(run_id)
    artifact = next((a for a in artifacts if a.id == artifact_id), None)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    signed = build_signed_url(artifact_id=artifact.id, object_url=artifact.url)
    return ArtifactSignedUrl(
        artifact_id=artifact.id,
        url=signed.url,
        kind=artifact.kind,
        scheme=signed.scheme,
        expires_at=signed.expires_at,
    )


@router.get("/runs/{run_id}/network", response_model=RunNetworkResponse)
async def get_run_network(
    run_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> RunNetworkResponse:
    """Network events captured during the run (M1b stub).

    Validates run-in-workspace scope (404 cross-workspace) and returns an empty
    page — HAR-driven event extraction lands with the runner in M1c. Frontend
    Network tab already renders the empty state today, so wiring this stub now
    means the screen stops 404-ing in real dev.
    """
    await _run_in_scope_or_404(session, run_id, ctx.workspace_id)
    return RunNetworkResponse(items=[])
