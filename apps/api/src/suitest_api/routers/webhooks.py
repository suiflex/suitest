"""Inbound webhook receivers — provider-specific endpoints under ``/api/v1/webhooks``.

M1d-17 ships the GitLab handler; M1d-16 (GitHub) and M1d-18 (Jira) plug into
the same router. All handlers share the helpers in
:mod:`suitest_api.services.webhook_receiver_service` for HMAC / token verify,
Redis SETNX dedup, and gating-suite selection resolution.

Webhook receivers run **without** the standard ``current_active_user`` /
``require_workspace_membership`` chain — authentication is via the provider's
signed-token header instead. Tenant scope (workspace) is resolved from the
:class:`Integration` row that owns the matching secret; project resolution then
falls under that workspace. Mis-signed requests return 401 *before* any DB
write so a credential-stuffing scan can't tax the dedup TTL.
"""

from __future__ import annotations

from typing import Annotated

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.audit import write_audit
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.runs import RunRepo
from suitest_shared.domain.enums import IntegrationKind, Role, RunTrigger

from suitest_api.auth.db import get_async_session
from suitest_api.deps.arq import get_arq
from suitest_api.deps.dedup_redis import get_dedup_redis
from suitest_api.deps.scope import TenantContext
from suitest_api.schemas.webhooks import (
    GitlabMergeRequestPayload,
    GitlabPushPayload,
    WebhookEnqueuedResponse,
    WebhookIgnoredResponse,
)
from suitest_api.services.run_service import RunService
from suitest_api.services.webhook_receiver_service import (
    resolve_gating_selection,
    resolve_project_from_payload,
    resolve_workspace_by_token,
    setnx_dedup,
)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


# ARQ queue name shared with the runner. Duplicated from
# :mod:`suitest_api.routers.runs` to avoid an unrelated import.
_RUNS_QUEUE = "suitest:runs"

# GitLab webhook event identifiers (the value sent in ``X-Gitlab-Event``).
_GITLAB_PUSH_EVENT = "Push Hook"
_GITLAB_MR_EVENT = "Merge Request Hook"
# Per plan-05b §M1d-17 only these MR actions enqueue a run.
_GITLAB_MR_ACTIONS_TRIGGERING_RUN: frozenset[str] = frozenset({"open", "reopen", "update"})


def _status_url(run_id: str) -> str:
    """Public status URL for the freshly-enqueued run.

    Kept relative so reverse-proxies in front of the api don't need to know the
    public host: clients append it to whatever base they're already using.
    """
    return f"/api/v1/runs/{run_id}"


@router.post(
    "/gitlab",
    responses={
        200: {"model": WebhookIgnoredResponse, "description": "Event accepted but no run enqueued"},
        202: {"model": WebhookEnqueuedResponse, "description": "Gating run enqueued"},
        401: {"description": "Token missing or mismatch"},
        404: {"description": "No matching project for the integration"},
    },
)
async def receive_gitlab(
    request: Request,
    response: Response,
    x_gitlab_token: Annotated[str | None, Header(alias="X-Gitlab-Token")] = None,
    x_gitlab_event: Annotated[str | None, Header(alias="X-Gitlab-Event")] = None,
    session: AsyncSession = Depends(get_async_session),
    arq: ArqRedis = Depends(get_arq),
    dedup_redis: object = Depends(get_dedup_redis),
) -> WebhookEnqueuedResponse | WebhookIgnoredResponse:
    """Handle a GitLab inbound webhook.

    Flow:

    1. Reject unsigned / wrong-token requests with 401 (constant-time compare
       lives in :func:`resolve_workspace_by_token`).
    2. Parse the payload according to ``X-Gitlab-Event``; unknown events return
       200 ``unsupported_event`` without enqueuing.
    3. Resolve the local project from the integration mapping; missing → 404.
    4. SETNX dedup over ``(project_id, commit_sha, trigger=WEBHOOK_GITLAB)``;
       duplicate → 200 ``duplicate``.
    5. Resolve the gating selection; empty → 200 ``no_gating_suite``.
    6. Enqueue a Run via :class:`RunService.create_run` with
       ``triggered_by="webhook:gitlab"`` and ``user_id=None``; return 202.
    """
    # ---- 1. token verify ---------------------------------------------------
    if not x_gitlab_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing X-Gitlab-Token"
        )
    tenant = await resolve_workspace_by_token(
        session, kind=IntegrationKind.GITLAB, token=x_gitlab_token
    )
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid X-Gitlab-Token"
        )

    # ---- 2. parse payload by event kind -----------------------------------
    raw_body = await request.json()
    branch: str | None
    commit_sha: str
    mr_iid: int | None = None
    external_project_id: int | None = None
    external_path: str | None = None
    name: str

    if x_gitlab_event == _GITLAB_PUSH_EVENT:
        try:
            push = GitlabPushPayload.model_validate(raw_body)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="invalid push payload"
            ) from exc
        branch = push.ref.removeprefix("refs/heads/") if push.ref else None
        commit_sha = push.commits[0].id if push.commits else (push.after or "")
        external_project_id = push.project.id if push.project is not None else push.project_id
        external_path = push.project.path_with_namespace if push.project is not None else None
        name = f"GitLab Push Hook: {branch}" if branch else "GitLab Push Hook"
    elif x_gitlab_event == _GITLAB_MR_EVENT:
        try:
            mr = GitlabMergeRequestPayload.model_validate(raw_body)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="invalid merge request payload"
            ) from exc
        action = (mr.object_attributes.action or "").lower()
        if action not in _GITLAB_MR_ACTIONS_TRIGGERING_RUN:
            response.status_code = status.HTTP_200_OK
            return WebhookIgnoredResponse(reason="unsupported_action")
        branch = mr.object_attributes.source_branch
        last_commit = mr.object_attributes.last_commit or {}
        commit_sha_raw = last_commit.get("id") if isinstance(last_commit, dict) else None
        commit_sha = commit_sha_raw if isinstance(commit_sha_raw, str) else ""
        mr_iid = mr.object_attributes.iid
        external_project_id = mr.project.id if mr.project is not None else None
        external_path = mr.project.path_with_namespace if mr.project is not None else None
        name = f"GitLab MR Hook !{mr_iid}: {branch}" if mr_iid else "GitLab MR Hook"
    else:
        response.status_code = status.HTTP_200_OK
        return WebhookIgnoredResponse(reason="unsupported_event")

    # ---- 3. project lookup -------------------------------------------------
    project = await resolve_project_from_payload(
        session,
        tenant=tenant,
        external_project_id=external_project_id,
        external_path=external_path,
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")

    trigger_label = RunTrigger.WEBHOOK.value

    # ---- 4. dedup ----------------------------------------------------------
    # ``dedup_redis`` is duck-typed as ``object`` so this module does not pin
    # the concrete redis client class on its import graph — the receiver
    # service's ``_RedisLike`` Protocol picks up the structural match.
    fresh = await setnx_dedup(
        dedup_redis,  # type: ignore[arg-type]
        project_id=project.id,
        commit_sha=commit_sha,
        trigger=trigger_label,
    )
    if not fresh:
        response.status_code = status.HTTP_200_OK
        return WebhookIgnoredResponse(reason="duplicate")

    # ---- 5. gating selection ----------------------------------------------
    selection = await resolve_gating_selection(session, project=project)
    if selection is None:
        response.status_code = status.HTTP_200_OK
        return WebhookIgnoredResponse(reason="no_gating_suite")

    # ---- 6. enqueue run + audit -------------------------------------------
    # Synthesise a TenantContext: the dataclass is frozen, but RunService only
    # reads ``ctx.workspace_id`` (and ``ctx.user_id`` for clone_for_rerun,
    # which webhook flows never call). ``role`` is set to OWNER as the
    # least-restrictive value since downstream code does not gate on it here.
    ctx = TenantContext(workspace_id=tenant.workspace_id, user_id="", role=Role.OWNER)
    svc = RunService(
        ctx=ctx,
        repo=RunRepo(session),
        project_repo=ProjectRepo(session),
    )
    try:
        run = await svc.create_run(
            project_id=project.id,
            name=name,
            selection=selection,
            branch=branch,
            commit_sha=commit_sha or None,
            env="staging",
            trigger=RunTrigger.WEBHOOK,
            user_id=None,
            mcp_routing_override=None,
            triggered_by="webhook:gitlab",
        )
    except ValueError as exc:
        # Selection contained a case that no longer resolves under the project
        # (e.g. soft-deleted between resolution and create_run). Surface as a
        # 200 ignored — webhook-receivers should not return 4xx for transient
        # data-race conditions a CI run would otherwise re-emit.
        response.status_code = status.HTTP_200_OK
        return WebhookIgnoredResponse(reason=f"selection_invalid: {exc}")

    job = await arq.enqueue_job("run_test_case", run.id, _queue_name=_RUNS_QUEUE)
    if job is not None:
        await svc.attach_arq_job_id(run.id, job.job_id)

    await write_audit(
        session,
        workspace_id=tenant.workspace_id,
        user_id=None,
        action="webhook.gitlab.received",
        resource_type="run",
        resource_id=run.id,
        metadata={
            "event": x_gitlab_event,
            "integration_id": tenant.integration.id,
            "external_project_id": external_project_id,
            "external_path": external_path,
            "branch": branch,
            "commit_sha": commit_sha or None,
            "merge_request_iid": mr_iid,
        },
    )

    await session.commit()
    response.status_code = status.HTTP_202_ACCEPTED
    return WebhookEnqueuedResponse(
        run_id=run.id, public_id=run.public_id, status_url=_status_url(run.id)
    )
