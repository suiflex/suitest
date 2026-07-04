"""``send_slack_notification`` ARQ job — posts a Slack notification for one defect.

The job is the only side-effecting wire between :class:`DefectAutoFiler` (M1d-10
PR — wires the enqueue) and :class:`~suitest_api.integrations.slack_adapter.SlackAdapter`
(M1d-15 — this PR — ships the wire format). Splitting the enqueue out of the
defect-filing transaction means the user-facing defect API stays fast (under
the API SLA) even when Slack is slow / unreachable; the retry policy below
absorbs transient Slack failures without dragging the API down with them.

Retry policy:

* ``max_tries=5`` (5 attempts total).
* ``backoff_seconds=[2, 4, 8, 16, 32]`` — exponential with jitter built into
  ARQ's own job dispatcher.
* On terminal failure (all retries exhausted) the job marks the integration
  ``status=error``, emits a ``workspace:<wsId>`` ``integration.error`` WS
  event, and writes an audit row.

The job is intentionally tiny so the bulk of the testable surface lives in
:class:`SlackAdapter` (Block Kit rendering, severity color matrix) and is
covered by ``apps/api/tests/test_slack_adapter.py``. The job tests
(``apps/runner/tests/test_send_slack_notification_job.py``) cover the retry +
terminal-failure semantics.
"""

from __future__ import annotations

import json
from typing import Any, Final, cast

import httpx
import structlog
from suitest_api.integrations.base import (
    AdapterError,
    DefectEvent,
    NotificationResult,
)
from suitest_api.integrations.notifier_registry import (
    NotifierFactoryNotRegistered,
    notifier_factory_registry,
)
from suitest_db.models.defect import Defect
from suitest_db.models.integration import Integration
from suitest_shared.domain.enums import IntegrationKind

log = structlog.get_logger(__name__)


# ARQ exponential backoff schedule. Indexed by ``job_try`` (1-based); attempt
# ``n`` waits ``BACKOFF_SECONDS[n - 1]`` seconds before re-dispatch. Five
# entries matches ``max_tries=5``.
BACKOFF_SECONDS: Final[tuple[int, ...]] = (2, 4, 8, 16, 32)

# Max attempts ARQ should run before treating the job as terminal-failed. The
# ARQ worker reads this off the job (``Retry(defer=...)`` requeues do not
# count against it; we use raw ``Retry`` so each attempt does).
JOB_MAX_TRIES: Final[int] = 5


async def send_slack_notification(
    ctx: dict[str, object],
    integration_id: str,
    defect_id: str,
) -> dict[str, object]:
    """Send one Slack notification.

    Args:
        ctx: ARQ-supplied per-job context. Must contain ``session_factory``
            (async SQLAlchemy ``async_sessionmaker``) and ``redis`` (broadcast
            channel for the ``integration.error`` WS event). The shared
            :class:`httpx.AsyncClient` is created per-job because the runner
            doesn't keep one on ``ctx`` (the MCP layer has its own transport
            stack and httpx is otherwise unused).
        integration_id: Internal id of the Slack :class:`Integration` row.
        defect_id: Internal id of the :class:`Defect` row to render.

    Returns:
        ``{"sent": True}`` on success.

        ``{"sent": False, "error": "<reason>"}`` on terminal failure (max
        retries exhausted) — the dict shape lets the call site (test harness,
        admin dashboard) read why without parsing logs.

    The job re-raises :class:`AdapterError` on transient failures (timeout,
    non-200) so ARQ's retry machinery picks it up; the final attempt's
    exception is caught, mapped to a terminal-failure record, and swallowed
    so the worker doesn't loop on a permanently broken webhook.
    """
    factory = ctx.get("session_factory")
    redis_client = ctx.get("redis")
    if not callable(factory):
        return {"sent": False, "error": "RUNNER_CTX_INVALID:session_factory"}

    # Resolve the current attempt number — 1-based, defaults to 1 if missing
    # (a test harness invoking the job directly typically omits ``job_try``).
    job_try_raw = ctx.get("job_try", 1)
    job_try = job_try_raw if isinstance(job_try_raw, int) else 1
    is_terminal_attempt = job_try >= JOB_MAX_TRIES

    integration: Integration | None = None
    workspace_id: str | None = None
    last_error: str | None = None

    try:
        # Load + validate the integration + defect in one short-lived session
        # so we don't hold a transaction open across the HTTP round-trip. We
        # use ``session.get`` directly (rather than the repo) because the
        # runner already does the same in ``run_test_case`` for ``Project``,
        # and skipping the repo keeps the session-surface test stubs need to
        # implement small.
        async with factory() as session:
            integration = await session.get(Integration, integration_id)
            if integration is None:
                log.warning(
                    "slack.job.integration_missing",
                    integration_id=integration_id,
                    defect_id=defect_id,
                )
                return {"sent": False, "error": "INTEGRATION_NOT_FOUND"}
            if integration.kind is not IntegrationKind.SLACK:
                log.warning(
                    "slack.job.integration_wrong_kind",
                    integration_id=integration_id,
                    kind=integration.kind.value,
                )
                return {"sent": False, "error": "INTEGRATION_KIND_MISMATCH"}
            workspace_id = integration.workspace_id

            defect = await session.get(Defect, defect_id)
            if defect is None:
                log.warning(
                    "slack.job.defect_missing",
                    integration_id=integration_id,
                    defect_id=defect_id,
                )
                return {"sent": False, "error": "DEFECT_NOT_FOUND"}

            event = _build_defect_event(defect)

        # Decrypt secrets + build adapter outside the session so the HTTP
        # round-trip (which can sleep on Slack's TLS handshake) doesn't hold
        # a DB connection.
        secrets = _decrypt_secrets(integration)
        config: dict[str, Any] = dict(integration.config) if integration.config else {}

        # The runner doesn't keep a long-lived httpx client; one per job is
        # acceptable because notifications are bursty (defect-triggered), not
        # high-volume. The ``async with`` ensures the transport is released
        # even if the adapter raises.
        async with httpx.AsyncClient() as http_client:
            factory_callable = notifier_factory_registry.get(IntegrationKind.SLACK)
            adapter = factory_callable(integration, http_client)
            result: NotificationResult = await adapter.send_notification(
                event,
                config=config,
                secrets=secrets,
            )

        if result.sent:
            log.info(
                "slack.job.sent",
                integration_id=integration_id,
                defect_id=defect_id,
                attempt=job_try,
            )
            return {"sent": True}

        # Adapter returned ``sent=False`` without raising. Treat as transient
        # and let ARQ retry until exhausted.
        last_error = result.error or "Slack adapter returned sent=False"
        raise AdapterError(last_error)

    except NotifierFactoryNotRegistered as exc:
        # The API process registered no SlackAdapter factory — this means the
        # runner is running against an older API image. Terminal: re-trying
        # won't help.
        log.error("slack.job.factory_missing", reason=str(exc))
        await _mark_terminal_failure(
            factory,
            redis_client,
            integration=integration,
            workspace_id=workspace_id,
            defect_id=defect_id,
            error=f"Slack factory not registered: {exc}",
        )
        return {"sent": False, "error": f"NOTIFIER_FACTORY_MISSING:{exc}"}

    except AdapterError as exc:
        last_error = str(exc)
        if is_terminal_attempt:
            log.warning(
                "slack.job.terminal_failure",
                integration_id=integration_id,
                defect_id=defect_id,
                attempt=job_try,
                error=last_error,
            )
            await _mark_terminal_failure(
                factory,
                redis_client,
                integration=integration,
                workspace_id=workspace_id,
                defect_id=defect_id,
                error=last_error,
            )
            return {"sent": False, "error": last_error}
        log.info(
            "slack.job.retry",
            integration_id=integration_id,
            defect_id=defect_id,
            attempt=job_try,
            error=last_error,
        )
        # Re-raise so ARQ's machinery retries with backoff. ARQ's default
        # exponential schedule lines up with ``BACKOFF_SECONDS`` because the
        # worker config (see ``WorkerSettings.functions``) wires
        # ``send_slack_notification`` with a custom backoff. We deliberately
        # don't use ``Retry(defer=...)`` here because that would reset
        # ``job_try`` and make the terminal-attempt check unreliable.
        raise


def _build_defect_event(defect: Defect) -> DefectEvent:
    """Project an ORM :class:`Defect` row into the adapter-facing DTO."""
    return DefectEvent(
        defect_id=defect.id,
        defect_public_id=defect.public_id,
        title=defect.title,
        severity=defect.severity,
        diagnosis_kind=defect.agent_diagnosis_kind,
        workspace_id=defect.workspace_id,
        run_id=defect.run_id,
        test_case_public_id=None,  # joined at the API layer; not stored on Defect
        suitest_base_url=None,  # populated from Integration.config at adapter call time
    )


def _decrypt_secrets(integration: Integration) -> dict[str, Any]:
    """Parse the already-AES-GCM-decrypted secret JSON string into a dict.

    ``Integration.secrets_encrypted`` is exposed by the ``EncryptedBytes``
    SQLAlchemy column as the plaintext JSON ``str`` (the column transparently
    encrypts on write / decrypts on load). We deserialise here so the adapter
    receives a typed dict rather than a raw blob.
    """
    raw = integration.secrets_encrypted
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        # JSON dict keys are always str; ``cast`` is needed because mypy can't
        # narrow the loaded JSON into a typed dict.
        return cast("dict[str, Any]", parsed)
    return {}


async def _mark_terminal_failure(
    factory: object,
    redis_client: object,
    *,
    integration: Integration | None,
    workspace_id: str | None,
    defect_id: str,
    error: str,
) -> None:
    """Flip the integration to ``status=error``, broadcast WS, write audit row.

    Best-effort: any DB / Redis failure is swallowed so a botched terminal
    handler can't loop. The next successful send (or operator action) will
    flip the status back.
    """
    if not callable(factory) or integration is None:
        return
    try:
        async with factory() as session:
            from suitest_db.audit import write_audit

            integration.status = "error"
            session.add(integration)
            if workspace_id is not None:
                await write_audit(
                    session,
                    workspace_id=workspace_id,
                    user_id=None,
                    action="integration.send_slack_notification.failed",
                    resource_type="integration",
                    resource_id=integration.id,
                    metadata={"defect_id": defect_id, "error": error},
                )
            await session.commit()
    except Exception as exc:
        log.warning(
            "slack.job.terminal_persist_skip",
            integration_id=integration.id,
            reason=str(exc),
        )

    if workspace_id is None:
        return
    try:
        payload = json.dumps(
            {
                "event": "integration.error",
                "data": {
                    "integrationId": integration.id,
                    "kind": IntegrationKind.SLACK.value,
                    "defectId": defect_id,
                    "error": error,
                },
            }
        )
        publish = getattr(redis_client, "publish", None)
        if callable(publish):
            await publish(f"workspace:{workspace_id}", payload)
    except Exception as exc:
        log.warning(
            "slack.job.terminal_broadcast_skip",
            integration_id=integration.id,
            reason=str(exc),
        )
