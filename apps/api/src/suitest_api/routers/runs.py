"""Run / run-step / log / artifact read endpoints (docs/API.md §3.5).

All scoped via project -> workspace. ``GET /runs/:id/logs`` concatenates each
RunStep's stdout + stderr in step_order into a flat line stream and paginates it
with a simple integer line-offset cursor (M1a; a richer per-chunk cursor lands
with live streaming in M3). Artifact download produces a presigned URL via
:func:`build_signed_url` (object store) or a placeholder for ``file://`` artifacts.
"""

from __future__ import annotations

import aioboto3
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.audit import write_audit
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.run_step_logs import RunStepLogRepo
from suitest_db.repositories.runs import RunRepo
from suitest_shared.domain.enums import RunStatus
from suitest_shared.schemas.pagination import Page, PageMeta

from suitest_api.auth.db import get_async_session
from suitest_api.deps.arq import get_arq
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.routers._pagination import decode_cursor_or_400, encode_next
from suitest_api.schemas.run import (
    ArtifactPublic,
    ArtifactSignedUrl,
    RunDetail,
    RunListItem,
    RunLogItem,
    RunLogPage,
    RunNetworkResponse,
    RunsSummary,
    RunStepPublic,
    RunSummary,
)
from suitest_api.schemas.runs import CreateRunBody, RunPublic
from suitest_api.services.run_service import RunService
from suitest_api.settings import get_settings

# ARQ queue name shared with the runner. Hardcoded here (vs. importing
# ``RunnerSettings``) so the api package does not depend on the runner package
# — runner is a separate process and its settings module pulls a redis client
# on import. Keep in sync with ``suitest_runner.worker.WorkerSettings.queue_name``.
_RUNS_QUEUE = "suitest:runs"

router = APIRouter(prefix="/api/v1", tags=["runs"])


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
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> RunLogPage:
    """Cursor-paginated slice of the orchestrator's persisted log stream (M1c).

    ``cursor`` is the last ``seq`` the client has already seen — pass ``0`` to
    fetch the head of the stream. Returns up to ``limit`` rows ordered ascending
    by ``seq`` plus the next ``seq`` for follow-up paging and a boolean
    ``hasMore`` so the FE knows when to stop polling. A request that returns
    fewer rows than ``limit`` is the natural EOF marker.
    """
    await _run_in_scope_or_404(session, run_id, ctx.workspace_id)
    rows = await RunStepLogRepo(session).list_after(run_id, cursor=cursor, limit=limit)
    items = [
        RunLogItem(seq=r.seq, level=r.level, message=r.message, created_at=r.created_at)
        for r in rows
    ]
    next_cursor = rows[-1].seq if rows else cursor
    return RunLogPage(items=items, next_cursor=next_cursor, has_more=len(rows) == limit)


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


_ARTIFACT_SIGNED_URL_TTL_SECONDS = 3600


@router.get("/runs/{run_id}/artifacts/{artifact_id}", response_model=ArtifactSignedUrl)
async def get_artifact_signed_url(
    run_id: str,
    artifact_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> ArtifactSignedUrl:
    """Return a real S3/MinIO presigned download URL for one artifact (M1c Task 18).

    Replaces the M1a stub presigner with an :mod:`aioboto3` ``generate_presigned_url``
    call against the configured bucket. Only ``s3://...`` artifacts are presigned —
    legacy ``file://`` artifacts (dev fixtures) return 404 here, the client should
    fall back to the static ``/artifacts/raw/`` route the static server exposes.
    Emits an ``artifact.signed_url`` audit row so download attribution is
    captured even though the actual fetch happens directly against S3.
    """
    await _run_in_scope_or_404(session, run_id, ctx.workspace_id)
    repo = RunRepo(session)
    artifacts = await repo.get_artifacts(run_id)
    artifact = next((a for a in artifacts if a.id == artifact_id), None)
    if artifact is None or not artifact.url.startswith("s3://"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    bucket, key = artifact.url.removeprefix("s3://").split("/", 1)

    settings = get_settings()
    session_factory = aioboto3.Session()
    async with session_factory.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    ) as client:
        url = await client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=_ARTIFACT_SIGNED_URL_TTL_SECONDS,
        )

    await write_audit(
        session,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        action="artifact.signed_url",
        resource_type="artifact",
        resource_id=artifact.id,
        metadata={"run_id": run_id},
    )
    await session.commit()
    return ArtifactSignedUrl(
        url=url,
        expires_in_seconds=_ARTIFACT_SIGNED_URL_TTL_SECONDS,
        kind=artifact.kind,
        mime_type=artifact.mime_type,
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


def _build_run_service(session: AsyncSession, ctx: TenantContext) -> RunService:
    """Compose a :class:`RunService` from a session + the resolved tenant scope.

    Both repos are workspace-aware via the service's ``_project_in_scope`` guard;
    the helper exists so the create / cancel / rerun handlers below stay one-liners
    and the next M1d endpoint added on top doesn't have to re-derive the wiring.
    """
    return RunService(ctx, RunRepo(session), ProjectRepo(session))


@router.post("/runs", response_model=RunPublic, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    body: CreateRunBody,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
    arq: ArqRedis = Depends(get_arq),
) -> RunPublic:
    """Validate selection + MCP routing, persist the run, enqueue the ARQ job.

    Returns 202 once the row exists and the job has been enqueued — the runner
    flips the status to ``RUNNING`` / ``PASS`` / ``FAIL`` asynchronously. The
    metadata blob carries the original selection so a rerun (or the orchestrator
    on resume) can rehydrate it without re-deriving suite ordering.
    """
    svc = _build_run_service(session, ctx)
    try:
        run = await svc.create_run(
            project_id=body.project_id,
            name=body.name,
            selection=[item.model_dump(by_alias=False) for item in body.selection],
            branch=body.branch,
            commit_sha=body.commit_sha,
            env=body.env,
            trigger=body.trigger,
            user_id=ctx.user_id,
            mcp_routing_override=body.mcp_routing_override,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    job = await arq.enqueue_job("run_test_case", run.id, _queue_name=_RUNS_QUEUE)
    if job is not None:
        await svc.attach_arq_job_id(run.id, job.job_id)
    await session.commit()
    await session.refresh(run)
    return RunPublic.model_validate(run)


# Statuses that ``POST /runs/:id/cancel`` will transition to CANCELLED. Any
# other status (PASS / FAIL / ERROR / CANCELLED) is terminal and returns 409.
_CANCELLABLE_STATUSES: frozenset[RunStatus] = frozenset({RunStatus.QUEUED, RunStatus.RUNNING})


@router.post("/runs/{run_id}/cancel", response_model=RunPublic)
async def cancel_run(
    run_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
    arq: ArqRedis = Depends(get_arq),
) -> RunPublic:
    """Transition a QUEUED / RUNNING run to CANCELLED and best-effort abort the ARQ job.

    The DB transition is authoritative — even if ARQ is unreachable, the run
    row flips to CANCELLED so the UI no longer shows it as live. We then try
    to abort the in-flight job (no-op if the job already completed / never
    started). Returns 409 when the run is already in a terminal state.
    """
    svc = _build_run_service(session, ctx)
    run = await svc.get(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    if run.status not in _CANCELLABLE_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="run not cancellable")
    metadata = run.metadata_json or {}
    job_id_raw = metadata.get("arq_job_id") if isinstance(metadata, dict) else None
    if isinstance(job_id_raw, str):
        try:
            from arq.jobs import Job as ArqJob

            await ArqJob(job_id_raw, arq, _queue_name=_RUNS_QUEUE).abort()
        except Exception:
            pass
    updated = await svc.update_status(run_id, RunStatus.CANCELLED)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    await session.commit()
    await session.refresh(updated)
    return RunPublic.model_validate(updated)


@router.post("/runs/{run_id}/rerun", response_model=RunPublic, status_code=status.HTTP_202_ACCEPTED)
async def rerun_run(
    run_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
    arq: ArqRedis = Depends(get_arq),
) -> RunPublic:
    """Clone the source run's selection into a fresh QUEUED row + enqueue the ARQ job.

    A rerun reuses the original selection + routing override (so the runner
    fans out identically) but re-resolves the workspace tier so a tier change
    between the two runs is honored. Returns 202 like the create endpoint.
    """
    svc = _build_run_service(session, ctx)
    src = await svc.get(run_id)
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    try:
        new_run = await svc.clone_for_rerun(src, user_id=ctx.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    job = await arq.enqueue_job("run_test_case", new_run.id, _queue_name=_RUNS_QUEUE)
    if job is not None:
        await svc.attach_arq_job_id(new_run.id, job.job_id)
    await session.commit()
    await session.refresh(new_run)
    return RunPublic.model_validate(new_run)
