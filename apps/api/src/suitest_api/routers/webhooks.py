"""Inbound webhook receivers — provider-specific endpoints under ``/api/v1/webhooks``.

M1d-16 ships the GitHub handler, M1d-17 the GitLab handler, and M1d-18 the
Jira ``issue_updated`` handler. All plug into the same router and share the
helpers in :mod:`suitest_api.services.webhook_receiver_service` for HMAC /
token / secret verify, Redis SETNX dedup, and gating-suite selection
resolution.

Webhook receivers run **without** the standard ``current_active_user`` /
``require_workspace_membership`` chain — authentication is per-provider:
GitHub/GitLab via signed-token header (HMAC); Jira via URL-embedded secret
(``?secret=<token>``) constant-time compared against
``Integration.config['webhook_secret']``. Tenant scope (workspace) is resolved
from the :class:`Integration` row that owns the matching secret; project
resolution then falls under that workspace. Mis-signed/mis-secret requests
return 401 *before* any DB write so a credential-stuffing scan can't tax the
dedup TTL or audit log.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, cast

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.audit import write_audit
from suitest_db.models.defect import Defect, ExternalIssue
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.runs import RunRepo
from suitest_shared.domain.enums import DefectStatus, IntegrationKind, Role, RunTrigger

from suitest_api.auth.db import get_async_session
from suitest_api.deps.arq import get_arq
from suitest_api.deps.dedup_redis import get_dedup_redis
from suitest_api.deps.scope import TenantContext
from suitest_api.integrations.base import IssueTrackerAdapter
from suitest_api.integrations.jira_adapter import JiraAdapter
from suitest_api.schemas.webhooks import (
    GithubPullRequestPayload,
    GithubPushPayload,
    GitlabMergeRequestPayload,
    GitlabPushPayload,
    JiraIssueUpdatedPayload,
    JiraSyncedResponse,
    WebhookEnqueuedResponse,
    WebhookIgnoredResponse,
    WebhookPingResponse,
)
from suitest_api.services.run_service import RunService
from suitest_api.services.webhook_receiver_service import (
    WebhookTenant,
    resolve_gating_selection,
    resolve_github_project,
    resolve_project_from_payload,
    resolve_workspace_by_secret,
    resolve_workspace_by_token,
    setnx_dedup,
    setnx_jira_dedup,
    verify_github_hmac,
)
from suitest_api.ws.publisher import publish_event

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


# ARQ queue name shared with the runner. Duplicated from
# :mod:`suitest_api.routers.runs` to avoid an unrelated import.
_RUNS_QUEUE = "suitest:runs"

# GitLab webhook event identifiers (the value sent in ``X-Gitlab-Event``).
_GITLAB_PUSH_EVENT = "Push Hook"
_GITLAB_MR_EVENT = "Merge Request Hook"
# Per plan-05b §M1d-17 only these MR actions enqueue a run.
_GITLAB_MR_ACTIONS_TRIGGERING_RUN: frozenset[str] = frozenset({"open", "reopen", "update"})

# GitHub webhook event identifiers (the value sent in ``X-GitHub-Event``).
_GITHUB_PING_EVENT = "ping"
_GITHUB_PUSH_EVENT = "push"
_GITHUB_PULL_REQUEST_EVENT = "pull_request"
# Per plan-05b §M1d-16 only these PR actions enqueue a run.
_GITHUB_PR_ACTIONS_TRIGGERING_RUN: frozenset[str] = frozenset({"opened", "synchronize", "reopened"})

# Stable string for the only Jira event we act on. Anything else short-circuits
# to a 200 ``unsupported_event`` reply so test/dev subscriptions firing every
# Jira event kind don't choke on missing handlers.
_JIRA_EVENT_ISSUE_UPDATED = "jira:issue_updated"

# Provider string stored on ``external_issues.provider`` for Jira-linked rows.
_JIRA_EXTERNAL_PROVIDER = "jira"

# Terminal :class:`DefectStatus` values — these flip ``resolved_at``. Anything
# else (re-open, in-progress) clears the column back to ``NULL``.
_TERMINAL_STATUSES: frozenset[DefectStatus] = frozenset(
    {DefectStatus.RESOLVED, DefectStatus.CLOSED}
)


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


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


@router.post(
    "/github",
    responses={
        200: {
            "description": (
                "Event accepted — either ``ping`` (`{pong: true}`) or an event "
                "the receiver intentionally drops (``{ignored: true, reason: ...}``)."
            ),
        },
        202: {"model": WebhookEnqueuedResponse, "description": "Gating run enqueued"},
        401: {"description": "Signature missing or HMAC mismatch"},
        404: {"description": "No matching project for the integration"},
    },
)
async def receive_github(
    request: Request,
    response: Response,
    x_hub_signature_256: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
    x_github_event: Annotated[str | None, Header(alias="X-GitHub-Event")] = None,
    x_github_delivery: Annotated[str | None, Header(alias="X-GitHub-Delivery")] = None,
    session: AsyncSession = Depends(get_async_session),
    arq: ArqRedis = Depends(get_arq),
    dedup_redis: object = Depends(get_dedup_redis),
) -> WebhookEnqueuedResponse | WebhookIgnoredResponse | WebhookPingResponse:
    """Handle a GitHub inbound webhook."""
    body_bytes = await request.body()

    if not x_hub_signature_256:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing X-Hub-Signature-256"
        )
    tenant = await verify_github_hmac(
        session, body=body_bytes, signature_header=x_hub_signature_256
    )
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid X-Hub-Signature-256"
        )

    if x_github_event == _GITHUB_PING_EVENT:
        response.status_code = status.HTTP_200_OK
        return WebhookPingResponse(pong=True)

    try:
        raw_body = await request.json()
    except ValueError as exc:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid json body"
        ) from exc

    branch: str | None
    commit_sha: str
    pr_number: int | None = None
    repo_full_name: str | None = None
    name: str

    if x_github_event == _GITHUB_PUSH_EVENT:
        try:
            push = GithubPushPayload.model_validate(raw_body)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="invalid push payload"
            ) from exc
        if push.deleted is True:
            response.status_code = status.HTTP_200_OK
            return WebhookIgnoredResponse(reason="branch_deleted")
        branch = push.ref.removeprefix("refs/heads/") if push.ref else None
        commit_sha = push.after or ""
        repo_full_name = push.repository.full_name if push.repository is not None else None
        name = f"GitHub Push: {branch}" if branch else "GitHub Push"
    elif x_github_event == _GITHUB_PULL_REQUEST_EVENT:
        try:
            pr = GithubPullRequestPayload.model_validate(raw_body)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="invalid pull_request payload"
            ) from exc
        action = (pr.action or "").lower()
        if action not in _GITHUB_PR_ACTIONS_TRIGGERING_RUN:
            response.status_code = status.HTTP_200_OK
            return WebhookIgnoredResponse(reason="unsupported_action")
        head = pr.pull_request.head if pr.pull_request is not None else None
        commit_sha = head.sha if head is not None and head.sha else ""
        branch = head.ref if head is not None else None
        pr_number = pr.number or (pr.pull_request.number if pr.pull_request is not None else None)
        repo_full_name = pr.repository.full_name if pr.repository is not None else None
        name = f"GitHub PR #{pr_number}: {branch}" if pr_number else "GitHub PR"
    else:
        response.status_code = status.HTTP_200_OK
        return WebhookIgnoredResponse(reason="unsupported_event")

    project = await resolve_github_project(session, tenant=tenant, repo_full_name=repo_full_name)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")

    trigger_label = RunTrigger.WEBHOOK.value

    fresh = await setnx_dedup(
        dedup_redis,  # type: ignore[arg-type]
        project_id=project.id,
        commit_sha=commit_sha,
        trigger=trigger_label,
    )
    if not fresh:
        response.status_code = status.HTTP_200_OK
        return WebhookIgnoredResponse(reason="duplicate")

    selection = await resolve_gating_selection(session, project=project)
    if selection is None:
        response.status_code = status.HTTP_200_OK
        return WebhookIgnoredResponse(reason="no_gating_suite")

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
            triggered_by="webhook:github",
        )
    except ValueError as exc:
        response.status_code = status.HTTP_200_OK
        return WebhookIgnoredResponse(reason=f"selection_invalid: {exc}")

    job = await arq.enqueue_job("run_test_case", run.id, _queue_name=_RUNS_QUEUE)
    if job is not None:
        await svc.attach_arq_job_id(run.id, job.job_id)

    await write_audit(
        session,
        workspace_id=tenant.workspace_id,
        user_id=None,
        action="webhook.github.received",
        resource_type="run",
        resource_id=run.id,
        metadata={
            "event": x_github_event,
            "delivery": x_github_delivery,
            "integration_id": tenant.integration.id,
            "repository": repo_full_name,
            "branch": branch,
            "commit_sha": commit_sha or None,
            "pull_request_number": pr_number,
        },
    )

    await session.commit()
    response.status_code = status.HTTP_202_ACCEPTED
    return WebhookEnqueuedResponse(
        run_id=run.id, public_id=run.public_id, status_url=_status_url(run.id)
    )


# ---------------------------------------------------------------------------
# Jira
# ---------------------------------------------------------------------------


@router.post(
    "/jira",
    responses={
        200: {
            "model": WebhookIgnoredResponse,
            "description": "Event accepted but no update applied",
        },
        202: {"model": JiraSyncedResponse, "description": "Defect status synced from Jira"},
        401: {"description": "Secret missing or mismatch"},
        400: {"description": "Payload failed schema validation"},
    },
)
async def receive_jira(
    request: Request,
    response: Response,
    secret: Annotated[str | None, Query(description="URL-embedded webhook secret")] = None,
    session: AsyncSession = Depends(get_async_session),
    dedup_redis: object = Depends(get_dedup_redis),
) -> JiraSyncedResponse | WebhookIgnoredResponse:
    """Handle an inbound Jira webhook (M1d-18)."""
    # ---- 1. secret verify --------------------------------------------------
    if not secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing secret")
    tenant = await resolve_workspace_by_secret(session, kind=IntegrationKind.JIRA, secret=secret)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid secret")

    # ---- 2. event filter (pre-validation) ----------------------------------
    raw_body_obj = await request.json()
    if not isinstance(raw_body_obj, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="payload must be a JSON object"
        )
    raw_body_jira: dict[str, object] = raw_body_obj
    event_name = raw_body_jira.get("webhookEvent")
    if event_name != _JIRA_EVENT_ISSUE_UPDATED:
        response.status_code = status.HTTP_200_OK
        return WebhookIgnoredResponse(reason="unsupported_event")

    # ---- 3. payload parse --------------------------------------------------
    try:
        payload = JiraIssueUpdatedPayload.model_validate(raw_body_jira)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid issue_updated payload"
        ) from exc

    issue_key = payload.issue.key
    status_name = ""
    if payload.issue.fields is not None and payload.issue.fields.status is not None:
        status_name = payload.issue.fields.status.name or ""
    changelog_id = (payload.changelog.id if payload.changelog is not None else None) or ""
    correlation_id = changelog_id or None

    # ---- 4. local defect lookup -------------------------------------------
    defect = await _find_workspace_defect_by_external_key(
        session, workspace_id=tenant.workspace_id, external_key=issue_key
    )
    if defect is None:
        response.status_code = status.HTTP_200_OK
        return WebhookIgnoredResponse(reason="unknown_issue")

    # ---- 5. status mapping via JiraAdapter --------------------------------
    if not status_name:
        response.status_code = status.HTTP_200_OK
        return WebhookIgnoredResponse(reason="unmappable_status")
    adapter = _build_jira_adapter(request, tenant)
    mapped_status = adapter.map_external_status_to_defect_status(status_name)
    if mapped_status is None:
        await write_audit(
            session,
            workspace_id=tenant.workspace_id,
            user_id=None,
            action="defect.status_sync_skipped_unmappable",
            resource_type="defect",
            resource_id=defect.id,
            metadata={
                "external_status_name": status_name,
                "external_id": issue_key,
                "integration_id": tenant.integration.id,
                "correlation_id": correlation_id,
            },
        )
        await session.commit()
        response.status_code = status.HTTP_200_OK
        return WebhookIgnoredResponse(reason="unmappable_status")

    # ---- 6. dedup ----------------------------------------------------------
    fresh_jira = await setnx_jira_dedup(
        dedup_redis,  # type: ignore[arg-type]
        workspace_id=tenant.workspace_id,
        issue_key=issue_key,
        changelog_id=changelog_id,
    )
    if not fresh_jira:
        response.status_code = status.HTTP_200_OK
        return WebhookIgnoredResponse(reason="duplicate")

    # ---- 7. idempotency: no change --------------------------------------
    from_status = defect.status
    if from_status == mapped_status:
        response.status_code = status.HTTP_200_OK
        return WebhookIgnoredResponse(reason="no_status_change")

    # ---- 8. mutate + audit + WS -----------------------------------------
    defect.status = mapped_status
    if mapped_status in _TERMINAL_STATUSES:
        if defect.resolved_at is None:
            defect.resolved_at = datetime.now(UTC)
    else:
        defect.resolved_at = None

    await write_audit(
        session,
        workspace_id=tenant.workspace_id,
        user_id=None,
        action="defect.status_synced_from_jira",
        resource_type="defect",
        resource_id=defect.id,
        metadata={
            "from_status": from_status.value,
            "to_status": mapped_status.value,
            "external_status_name": status_name,
            "external_id": issue_key,
            "integration_id": tenant.integration.id,
            "correlation_id": correlation_id,
        },
    )
    await session.commit()

    await publish_event(
        request,
        topic=f"workspace:{tenant.workspace_id}",
        event="defect.updated",
        data={
            "defectId": defect.id,
            "status": mapped_status.value,
            "severity": defect.severity.value,
            "assigneeUserId": str(defect.assignee_id) if defect.assignee_id else None,
        },
    )

    response.status_code = status.HTTP_202_ACCEPTED
    return JiraSyncedResponse(
        defect_id=defect.id,
        from_status=from_status.value,
        to_status=mapped_status.value,
    )


# ---------------------------------------------------------------------------
# Internal helpers (Jira)
# ---------------------------------------------------------------------------


async def _find_workspace_defect_by_external_key(
    session: AsyncSession, *, workspace_id: str, external_key: str
) -> Defect | None:
    """Resolve the local :class:`Defect` for a Jira issue key, workspace-scoped."""
    stmt = (
        select(Defect)
        .join(ExternalIssue, ExternalIssue.defect_id == Defect.id)
        .where(
            ExternalIssue.provider == _JIRA_EXTERNAL_PROVIDER,
            ExternalIssue.external_id == external_key,
            Defect.workspace_id == workspace_id,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def _build_jira_adapter(request: Request, tenant: WebhookTenant) -> IssueTrackerAdapter:
    """Construct a :class:`JiraAdapter` for the resolved tenant integration."""
    factories = getattr(request.app.state, "adapter_factories", None)
    crypto = getattr(request.app.state, "integration_crypto", None)
    factory: Any = JiraAdapter
    if isinstance(factories, dict):
        candidate = factories.get(IntegrationKind.JIRA)
        if candidate is not None:
            factory = candidate
    if crypto is None:
        from suitest_api.integrations.jira_adapter import _IdentityCrypto

        crypto = _IdentityCrypto()
    return cast(
        "IssueTrackerAdapter",
        factory(
            integration=tenant.integration,
            mcp_client=_NoopMcpClient(),
            crypto=crypto,
        ),
    )


class _NoopMcpClient:
    """Stub MCP client for the status-map-only call path."""

    async def invoke(
        self,
        *,
        provider: str,
        tool: str,
        arguments: dict[str, object],
        env_overrides: dict[str, str],
    ) -> dict[str, object]:
        raise RuntimeError(
            "JiraAdapter MCP client invoked from the webhook receiver — "
            "the receiver only uses the pure-Python status map; reaching this "
            "path means a future code change tried to call a remote Jira tool "
            "without wiring a real MCP client"
        )
