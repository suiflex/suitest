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
    """Handle a GitHub inbound webhook.

    Flow:

    1. Reject unsigned / wrong-HMAC requests with 401 (constant-time compare
       lives in :func:`verify_github_hmac`). The raw request body is read once
       and reused for both the signature check and JSON parse so the bytes
       hashed match the bytes GitHub signed.
    2. ``X-GitHub-Event: ping`` → 200 ``{pong: true}`` (no Run).
    3. ``push`` → enqueue a gating run on ``after``. ``ref`` becomes the
       branch label (``refs/heads/main`` → ``main``).
    4. ``pull_request`` with action in ``{opened, synchronize, reopened}`` →
       enqueue a gating run on ``pull_request.head.sha``; other actions
       (``closed``, ``labeled``, …) return 200 ``unsupported_action``.
    5. Other events → 200 ``unsupported_event``.
    6. Unknown repo (``github_repo`` mismatch or project absent) → 404.
    7. SETNX dedup over ``(project_id, commit_sha, trigger=WEBHOOK)`` keeps
       PR ``synchronize`` from re-firing inside the TTL when GitHub retries.
    """
    # ---- 0. read body once for HMAC + JSON parse --------------------------
    body_bytes = await request.body()

    # ---- 1. HMAC verify ---------------------------------------------------
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

    # ---- 2. ping → short circuit ------------------------------------------
    if x_github_event == _GITHUB_PING_EVENT:
        response.status_code = status.HTTP_200_OK
        return WebhookPingResponse(pong=True)

    # ---- 3. parse payload by event kind -----------------------------------
    try:
        raw_body = await request.json()
    except ValueError as exc:  # pragma: no cover — FastAPI surfaces this
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
        # GitHub sets ``deleted=true`` for branch deletes — we don't gate on
        # those because ``after`` will be the zero-SHA and the runner has
        # nothing to check out.
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

    # ---- 4. project lookup -------------------------------------------------
    project = await resolve_github_project(session, tenant=tenant, repo_full_name=repo_full_name)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")

    trigger_label = RunTrigger.WEBHOOK.value

    # ---- 5. dedup ----------------------------------------------------------
    fresh = await setnx_dedup(
        dedup_redis,  # type: ignore[arg-type]
        project_id=project.id,
        commit_sha=commit_sha,
        trigger=trigger_label,
    )
    if not fresh:
        response.status_code = status.HTTP_200_OK
        return WebhookIgnoredResponse(reason="duplicate")

    # ---- 6. gating selection ----------------------------------------------
    selection = await resolve_gating_selection(session, project=project)
    if selection is None:
        response.status_code = status.HTTP_200_OK
        return WebhookIgnoredResponse(reason="no_gating_suite")

    # ---- 7. enqueue run + audit -------------------------------------------
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
        # See the GitLab handler: a soft-deleted case between selection +
        # create_run is a transient race CI will re-emit, so we soft-fail to
        # 200 ignored rather than a hard 4xx.
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
    """Handle an inbound Jira webhook.

    Flow:

    1. Reject missing / wrong ``?secret=`` with 401 (constant-time compare
       lives in :func:`resolve_workspace_by_secret`).
    2. Short-circuit any ``webhookEvent`` other than ``jira:issue_updated`` to
       a 200 ``unsupported_event`` reply *before* schema validation — Jira
       fires every event kind a subscription is subscribed to and we don't
       want a `jira:issue_created` payload missing a `changelog` block to
       422.
    3. Validate the body as :class:`JiraIssueUpdatedPayload`; malformed →
       400.
    4. Look up the local :class:`Defect` via its :class:`ExternalIssue` row
       keyed on ``provider="jira" AND external_id == payload.issue.key``.
       Scoped to the resolved tenant's ``workspace_id`` so a Jira webhook
       subscribed in workspace A can never bleed into workspace B's defects
       (404 → 200 ``unknown_issue``).
    5. Resolve the :class:`JiraAdapter` for this Integration via
       ``app.state.adapter_factories``, then map the inbound external status
       name → :class:`DefectStatus`. Unmappable → 200 ``unmappable_status`` +
       audit ``defect.status_sync_skipped_unmappable``.
    6. SETNX dedup over ``(workspace_id, issue_key, changelog_id)``; duplicate
       → 200 ``duplicate``.
    7. If mapped status == current ``defect.status`` → 200 ``no_status_change``
       (idempotent — Jira replay / status edit that didn't move the workflow).
    8. Else mutate the row: ``defect.status``, flip ``resolved_at`` (now() on
       terminal, ``None`` on non-terminal), audit ``defect.status_synced_from_jira``,
       commit, then emit ``defect.updated`` WS to the workspace room. Return
       202 + the new status.
    """
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
    raw_body: dict[str, object] = raw_body_obj
    event_name = raw_body.get("webhookEvent")
    if event_name != _JIRA_EVENT_ISSUE_UPDATED:
        response.status_code = status.HTTP_200_OK
        return WebhookIgnoredResponse(reason="unsupported_event")

    # ---- 3. payload parse --------------------------------------------------
    try:
        payload = JiraIssueUpdatedPayload.model_validate(raw_body)
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
        # No status field shipped — nothing to map. Treat as ignored rather
        # than 400 because Jira sometimes ships an `issue_updated` for label
        # changes with the status block elided.
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
    # ``dedup_redis`` is typed as ``object`` on the dep so the import graph
    # stays free of :mod:`redis.asyncio` — the receiver service's ``_RedisLike``
    # Protocol picks up the structural ``set(name, value, *, nx, ex)`` match.
    fresh = await setnx_jira_dedup(
        dedup_redis,  # type: ignore[arg-type]
        workspace_id=tenant.workspace_id,
        issue_key=issue_key,
        changelog_id=changelog_id,
    )
    if not fresh:
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
        # Only set resolved_at on the transition INTO a terminal state so
        # repeated mutations within a terminal state don't drift the column.
        if defect.resolved_at is None:
            defect.resolved_at = datetime.now(UTC)
    else:
        # Re-opening a closed/resolved defect clears the timestamp — the
        # value is meaningful only while the row is in a terminal state.
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
# Internal helpers
# ---------------------------------------------------------------------------


async def _find_workspace_defect_by_external_key(
    session: AsyncSession, *, workspace_id: str, external_key: str
) -> Defect | None:
    """Resolve the local :class:`Defect` for a Jira issue key, workspace-scoped.

    Joins ``external_issues`` on ``provider='jira' AND external_id=<key>`` and
    re-checks the ``defects.workspace_id`` so a Jira webhook in workspace A
    cannot ever mutate a defect linked in workspace B (the unique constraint
    on ``(provider, external_id)`` already prevents a single Jira issue from
    pointing at two defects, but the workspace re-check stays as a
    defense-in-depth seam in case the constraint is ever relaxed).
    """
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
    """Construct a :class:`JiraAdapter` for the resolved tenant integration.

    The factory lives on ``app.state.adapter_factories[IntegrationKind.JIRA]``
    (wired by the lifespan in :mod:`suitest_api.main`). We resolve through
    the factory rather than calling :class:`JiraAdapter` directly so a future
    swap-in (e.g. a mocked adapter in tests, or an alternative Jira backend)
    works through the same seam the rest of the integration code uses.

    The MCP client is wired with a no-op stub since this receiver only calls
    :meth:`JiraAdapter.map_external_status_to_defect_status`, which is pure
    Python — no MCP round-trip required.
    """
    factories = getattr(request.app.state, "adapter_factories", None)
    crypto = getattr(request.app.state, "integration_crypto", None)
    # ``factories`` is dict[IntegrationKind, type] on app.state but we keep the
    # type loose here (``Any``) so the call site survives a future widening of
    # the factory signature (e.g. a partial that pre-binds the MCP client).
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
    """Stub MCP client for the status-map-only call path.

    :meth:`JiraAdapter.map_external_status_to_defect_status` is pure Python
    (it touches the in-memory :class:`StatusMap` built at adapter init) so
    the MCP client is never invoked. We still need to pass *something* that
    satisfies the ``JiraMcpClient`` Protocol; this raises loudly if the
    invariant is ever broken so the bug doesn't silently land in production
    as a stale-mock false negative.
    """

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
