"""``file_external_issue`` ARQ job — delegates defect → external tracker.

Enqueued by :class:`~suitest_api.services.defect_auto_filer.DefectAutoFiler`
after the system-filed defect is committed. The job looks up the workspace's
integration row, resolves an :class:`~suitest_api.integrations.base.IssueTrackerAdapter`
from the process-wide :data:`adapter_registry`, and asks the adapter to
create the upstream issue (Jira ticket, Linear issue, GitHub issue, …).

The job is intentionally tiny — every wire-format concern (auth, request
shape, retry of upstream 429s) lives inside the concrete adapter (M1d-12..14).
This job's only responsibilities are:

* Loading the defect + integration rows in a short-lived session.
* Validating the integration is the right kind + still ``active``.
* Calling :meth:`IssueTrackerAdapter.create_external_issue` with a typed DTO.
* Persisting the resulting :class:`ExternalIssue` link row so defect → issue
  is reflected back in Suitest's UI.

A terminal failure here does NOT poison the defect — the defect row stays
filed and the operator can re-sync from the Defects page. The job catches
:class:`AdapterError` and writes an ``integration.file_external_issue.failed``
audit row so the failure is visible in the audit timeline.
"""

from __future__ import annotations

from typing import Final

import httpx
import structlog
from suitest_api.integrations.base import (
    AdapterError,
    ExternalIssueInput,
    IssueTrackerAdapter,
)
from suitest_api.integrations.registry import (
    AdapterNotRegistered,
    adapter_registry,
)
from suitest_db.audit import write_audit
from suitest_db.models.case import TestCase
from suitest_db.models.defect import Defect, ExternalIssue
from suitest_db.models.integration import Integration
from suitest_shared.domain.enums import IntegrationKind

log = structlog.get_logger(__name__)


# Per-attempt timeout. Generous compared to Slack because issue trackers
# (Jira, GitHub) frequently have multi-second p99s under load.
DEFAULT_HTTP_TIMEOUT_SECONDS: Final[float] = 15.0


async def file_external_issue(
    ctx: dict[str, object],
    integration_id: str,
    defect_id: str,
) -> dict[str, object]:
    """File one external issue for the given defect via the workspace integration.

    Args:
        ctx: ARQ-supplied per-job context. Must contain ``session_factory``
            (async SQLAlchemy ``async_sessionmaker``). The adapter registry is
            consulted via the process-wide singleton in
            :mod:`suitest_api.integrations.registry`.
        integration_id: Internal id of the :class:`Integration` row.
        defect_id: Internal id of the :class:`Defect` row to file upstream.

    Returns:
        ``{"filed": True, "external_id": ..., "external_url": ...}`` on
        success.

        ``{"filed": False, "error": "<reason>"}`` on terminal failure (no
        adapter registered, integration missing, defect missing, adapter
        raised :class:`AdapterError`). The dict shape lets the call site
        (test harness, admin dashboard) read why without parsing logs.
    """
    factory = ctx.get("session_factory")
    if not callable(factory):
        return {"filed": False, "error": "RUNNER_CTX_INVALID:session_factory"}

    integration: Integration | None = None
    defect: Defect | None = None
    workspace_id: str | None = None
    case_public_id: str | None = None

    # Load the rows in one short-lived session — we don't hold the
    # transaction across the HTTP round-trip.
    async with factory() as session:
        integration = await session.get(Integration, integration_id)
        if integration is None:
            log.warning(
                "external_issue.job.integration_missing",
                integration_id=integration_id,
                defect_id=defect_id,
            )
            return {"filed": False, "error": "INTEGRATION_NOT_FOUND"}
        if integration.kind not in {
            IntegrationKind.JIRA,
            IntegrationKind.LINEAR,
            IntegrationKind.GITHUB,
            IntegrationKind.GITLAB,
        }:
            log.warning(
                "external_issue.job.integration_wrong_kind",
                integration_id=integration_id,
                kind=integration.kind.value,
            )
            return {"filed": False, "error": "INTEGRATION_KIND_MISMATCH"}
        workspace_id = integration.workspace_id

        defect = await session.get(Defect, defect_id)
        if defect is None:
            log.warning(
                "external_issue.job.defect_missing",
                integration_id=integration_id,
                defect_id=defect_id,
            )
            return {"filed": False, "error": "DEFECT_NOT_FOUND"}

        if defect.test_case_id is not None:
            case = await session.get(TestCase, defect.test_case_id)
            if case is not None:
                case_public_id = case.public_id

    # Look up the adapter outside the session — the registry is a
    # process-wide singleton, no DB needed.
    try:
        adapter: IssueTrackerAdapter = adapter_registry.get(integration.kind)
    except AdapterNotRegistered as exc:
        log.warning(
            "external_issue.job.adapter_not_registered",
            kind=integration.kind.value,
            reason=str(exc),
        )
        return {
            "filed": False,
            "error": f"ADAPTER_NOT_REGISTERED:{integration.kind.value}",
        }

    body = ExternalIssueInput(
        defect_id=defect.id,
        title=defect.title,
        description=defect.description or "",
        severity=defect.severity,
        run_id=defect.run_id,
        test_case_public_id=case_public_id,
    )

    try:
        # The adapter is responsible for its own httpx client lifecycle in
        # production. We hand it nothing here — concrete adapters (Jira /
        # Linear / GitHub) construct their own clients per-call or share a
        # process-singleton; either way the call site stays one line.
        external_issue = await adapter.create_external_issue(body)
    except AdapterError as exc:
        log.warning(
            "external_issue.job.adapter_error",
            integration_id=integration_id,
            defect_id=defect_id,
            kind=integration.kind.value,
            error=str(exc),
        )
        await _audit_failure(
            factory,
            workspace_id=workspace_id,
            integration_id=integration_id,
            defect_id=defect_id,
            error=str(exc),
        )
        return {"filed": False, "error": f"ADAPTER_ERROR:{exc}"}

    # Persist the link row so the defect detail page renders the upstream
    # issue link. Independent transaction so an adapter that succeeded
    # upstream isn't lost to a DB blip here.
    async with factory() as session:
        link = ExternalIssue(
            defect_id=defect.id,
            provider=integration.kind.value.lower(),
            external_id=external_issue.external_id,
            external_url=external_issue.external_url,
        )
        session.add(link)
        if workspace_id is not None:
            await write_audit(
                session,
                workspace_id=workspace_id,
                user_id=None,
                action="defect.file_external_issue.succeeded",
                resource_type="defect",
                resource_id=defect.id,
                metadata={
                    "integration_id": integration_id,
                    "kind": integration.kind.value,
                    "external_id": external_issue.external_id,
                    "external_url": external_issue.external_url,
                },
            )
        await session.commit()

    log.info(
        "external_issue.job.filed",
        integration_id=integration_id,
        defect_id=defect_id,
        kind=integration.kind.value,
        external_id=external_issue.external_id,
    )
    return {
        "filed": True,
        "external_id": external_issue.external_id,
        "external_url": external_issue.external_url,
    }


async def _audit_failure(
    factory: object,
    *,
    workspace_id: str | None,
    integration_id: str,
    defect_id: str,
    error: str,
) -> None:
    """Best-effort audit row write for a terminal adapter failure."""
    if not callable(factory) or workspace_id is None:
        return
    try:
        async with factory() as session:
            await write_audit(
                session,
                workspace_id=workspace_id,
                user_id=None,
                action="defect.file_external_issue.failed",
                resource_type="defect",
                resource_id=defect_id,
                metadata={"integration_id": integration_id, "error": error},
            )
            await session.commit()
    except Exception as exc:  # pragma: no cover — logged, swallowed
        log.warning(
            "external_issue.job.audit_skip",
            integration_id=integration_id,
            defect_id=defect_id,
            reason=str(exc),
        )


# httpx is imported eagerly so the module's importability matches the rest of
# the runner (artifacts.py, send_slack_notification.py both pull in httpx /
# aioboto3 at import time). Touch the binding so ruff doesn't flag the unused
# import — the production extension points (sub-adapters constructed per
# call) frequently rely on httpx being already in the import graph.
_ = httpx
