"""Inbound webhook receivers — provider-specific endpoints under ``/api/v1/webhooks``.

M1d-18 ships the Jira ``issue_updated`` handler. M1d-16 (GitHub) and M1d-17
(GitLab) will plug into the same router (and the same
:mod:`suitest_api.services.webhook_receiver_service` helpers) when those PRs
land on this branch line.

Webhook receivers run **without** the standard ``current_active_user`` /
``require_workspace_membership`` chain — authentication is via a per-provider
secret instead. Jira webhooks have no HMAC header so we use a URL-embedded
secret (``?secret=<token>``), constant-time compared against
``Integration.config['webhook_secret']``. Tenant scope (workspace) is resolved
from the :class:`Integration` row that owns the matching secret. Mis-secret
requests return 401 *before* any DB write so a credential-stuffing scan can't
tax the dedup TTL or audit log.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.audit import write_audit
from suitest_db.models.defect import Defect, ExternalIssue
from suitest_shared.domain.enums import DefectStatus, IntegrationKind

from suitest_api.auth.db import get_async_session
from suitest_api.deps.dedup_redis import get_dedup_redis
from suitest_api.integrations.base import IssueTrackerAdapter
from suitest_api.integrations.jira_adapter import JiraAdapter
from suitest_api.schemas.webhooks import (
    JiraIssueUpdatedPayload,
    JiraSyncedResponse,
    WebhookIgnoredResponse,
)
from suitest_api.services.webhook_receiver_service import (
    WebhookTenant,
    resolve_workspace_by_secret,
    setnx_jira_dedup,
)
from suitest_api.ws.publisher import publish_event

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


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
