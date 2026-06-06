"""``dispatch_webhook`` ARQ job — durable retry dispatcher (M4-31).

Dispatch side of :class:`~suitest_api.services.webhook_retry_queue.WebhookRetryQueue`.
Reads one ``webhook_dispatch_attempts`` ledger row (by id), performs the
outbound call via the existing integration adapters, and records the outcome
back onto the row. Unlike ``send_slack_notification`` (which leans on ARQ's
internal retry), this job owns the retry state explicitly in the DB so the UI
can surface the dead-letter state (``integration.status = error``).

Outcome → ledger transition:

* success → ``status=succeeded`` (terminal).
* transient :class:`AdapterError` (rate-limit / timeout / 5xx) → ``status=failed``,
  ``next_retry_at`` set, re-enqueued via ``_defer_by`` UNLESS the attempt budget
  (:data:`MAX_ATTEMPTS`) is exhausted, in which case → dead-letter.
* :class:`AdapterAuthError` (bad creds — retrying can't help) → dead-letter now.

Dead-letter flips the integration to ``status=error``, writes an audit row, and
emits a ``workspace:<id>`` ``integration.error`` WS event so the Integrations
grid shows the broken state without a refresh.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import httpx
import structlog
from suitest_api.integrations.base import (
    AdapterAuthError,
    AdapterError,
    DefectEvent,
    ExternalIssueInput,
)
from suitest_api.integrations.notifier_registry import (
    NotifierFactoryNotRegistered,
    notifier_factory_registry,
)
from suitest_api.integrations.registry import AdapterNotRegistered, adapter_registry
from suitest_api.services.webhook_retry_queue import (
    DISPATCH_QUEUE,
    MAX_ATTEMPTS,
    backoff_for,
)
from suitest_db.audit import write_audit
from suitest_db.models.integration import Integration
from suitest_db.models.webhook_dispatch import WebhookDispatchAttempt

if TYPE_CHECKING:
    from suitest_shared.domain.enums import IntegrationKind

log = structlog.get_logger(__name__)


async def dispatch_webhook(ctx: dict[str, object], attempt_id: str) -> dict[str, object]:
    """Dispatch one queued webhook attempt; record + reschedule per outcome."""
    factory = ctx.get("session_factory")
    redis_client = ctx.get("redis")
    arq_pool = ctx.get("arq_pool")
    if not callable(factory):
        return {"dispatched": False, "error": "RUNNER_CTX_INVALID:session_factory"}

    # Load the ledger row + integration. Capture the immutable fields we need
    # for dispatch so we don't hold the session across the HTTP round-trip.
    async with factory() as session:
        attempt = await session.get(WebhookDispatchAttempt, attempt_id)
        if attempt is None:
            return {"dispatched": False, "error": "ATTEMPT_NOT_FOUND"}
        if attempt.status in {"succeeded", "dead_letter"}:
            # Already terminal — a duplicate enqueue. No-op.
            return {"dispatched": False, "error": f"ATTEMPT_TERMINAL:{attempt.status}"}

        integration = await session.get(Integration, attempt.integration_id)
        if integration is None:
            attempt.status = "dead_letter"
            attempt.last_error = "INTEGRATION_NOT_FOUND"
            await session.commit()
            return {"dispatched": False, "error": "INTEGRATION_NOT_FOUND"}

        attempt.attempt_n += 1
        this_attempt = attempt.attempt_n
        operation = attempt.operation
        payload = dict(attempt.payload_json)
        kind = integration.kind
        config: dict[str, Any] = dict(integration.config) if integration.config else {}
        secrets = _decrypt_secrets(integration)
        await session.commit()

    # Perform the outbound call outside the session.
    try:
        await _dispatch(
            operation,
            kind=kind,
            integration=integration,
            config=config,
            secrets=secrets,
            payload=payload,
        )
    except AdapterAuthError as exc:
        await _dead_letter(factory, redis_client, attempt_id, integration, str(exc))
        return {"dispatched": False, "error": f"ADAPTER_AUTH_ERROR:{exc}"}
    except (AdapterError, NotifierFactoryNotRegistered, AdapterNotRegistered) as exc:
        if this_attempt >= MAX_ATTEMPTS:
            await _dead_letter(factory, redis_client, attempt_id, integration, str(exc))
            return {"dispatched": False, "error": f"EXHAUSTED:{exc}"}
        await _reschedule(factory, arq_pool, attempt_id, this_attempt, str(exc))
        return {"dispatched": False, "error": f"RETRY:{exc}", "attempt": this_attempt}

    # Success.
    async with factory() as session:
        row = await session.get(WebhookDispatchAttempt, attempt_id)
        if row is not None:
            row.status = "succeeded"
            row.succeeded_at = datetime.now(UTC)
            row.last_error = None
            row.next_retry_at = None
        await session.commit()
    log.info(
        "webhook.dispatch.ok", attempt_id=attempt_id, operation=operation, attempt=this_attempt
    )
    return {"dispatched": True, "attempt": this_attempt}


async def _dispatch(
    operation: str,
    *,
    kind: IntegrationKind,
    integration: Integration,
    config: dict[str, Any],
    secrets: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    """Route to the right adapter call for ``operation``. Raises on failure."""
    if operation == "send_notification":
        async with httpx.AsyncClient() as http_client:
            factory_callable = notifier_factory_registry.get(kind)
            adapter = factory_callable(integration, http_client)
            event = DefectEvent.model_validate(payload)
            result = await adapter.send_notification(event, config=config, secrets=secrets)
        if not result.sent:
            raise AdapterError(result.error or "notifier returned sent=False")
        return

    if operation == "file_external_issue":
        tracker = adapter_registry.get(kind)
        body = ExternalIssueInput.model_validate(payload)
        await tracker.create_external_issue(body)
        return

    if operation == "sync_status":
        tracker = adapter_registry.get(kind)
        from suitest_shared.domain.enums import DefectStatus

        external_key = str(payload["external_key"])
        new_status = DefectStatus(str(payload["new_status"]))
        await tracker.transition_status(external_key, new_status)
        return

    raise AdapterError(f"UNKNOWN_OPERATION:{operation}")


async def _reschedule(
    factory: object,
    arq_pool: object,
    attempt_id: str,
    attempt_n: int,
    error: str,
) -> None:
    """Mark failed + set ``next_retry_at`` and re-enqueue with backoff defer."""
    delay = backoff_for(attempt_n)
    if not callable(factory):
        return
    async with factory() as session:
        row = await session.get(WebhookDispatchAttempt, attempt_id)
        if row is not None:
            row.status = "failed"
            row.last_error = error[:2000]
            row.next_retry_at = datetime.now(UTC) + timedelta(seconds=delay)
        await session.commit()
    enqueue = getattr(arq_pool, "enqueue_job", None)
    if callable(enqueue):
        try:
            await enqueue(
                "dispatch_webhook",
                attempt_id,
                _queue_name=DISPATCH_QUEUE,
                _defer_by=delay,
            )
        except Exception as exc:  # pragma: no cover — logged, swallowed
            log.warning("webhook.dispatch.reenqueue_skip", attempt_id=attempt_id, reason=str(exc))
    log.info("webhook.dispatch.retry", attempt_id=attempt_id, attempt=attempt_n, defer_s=delay)


async def _dead_letter(
    factory: object,
    redis_client: object,
    attempt_id: str,
    integration: Integration,
    error: str,
) -> None:
    """Terminal failure: mark dead-letter, flip integration → error, audit + WS."""
    if not callable(factory):
        return
    async with factory() as session:
        row = await session.get(WebhookDispatchAttempt, attempt_id)
        workspace_id: str | None = None
        if row is not None:
            row.status = "dead_letter"
            row.last_error = error[:2000]
            row.next_retry_at = None
            workspace_id = row.workspace_id
        live = await session.get(Integration, integration.id)
        if live is not None:
            live.status = "error"
        if workspace_id is not None:
            await write_audit(
                session,
                workspace_id=workspace_id,
                user_id=None,
                action="integration.webhook.dead_letter",
                resource_type="integration",
                resource_id=integration.id,
                metadata={"attempt_id": attempt_id, "error": error[:500]},
            )
        await session.commit()
    await _publish_integration_error(redis_client, integration)
    log.error("webhook.dispatch.dead_letter", attempt_id=attempt_id, integration_id=integration.id)


async def _publish_integration_error(redis_client: object, integration: Integration) -> None:
    """Best-effort ``integration.error`` WS event on the workspace channel."""
    publish = getattr(redis_client, "publish", None)
    if not callable(publish):
        return
    channel = f"workspace:{integration.workspace_id}"
    message = json.dumps(
        {
            "type": "integration.error",
            "integration_id": integration.id,
            "kind": integration.kind.value,
        }
    )
    try:
        await publish(channel, message)
    except Exception as exc:  # pragma: no cover — logged, swallowed
        log.warning("webhook.dispatch.ws_skip", integration_id=integration.id, reason=str(exc))


def _decrypt_secrets(integration: Integration) -> dict[str, Any]:
    """Parse the AES-GCM-decrypted secret JSON string into a dict (mirrors slack job)."""
    raw = integration.secrets_encrypted
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return cast("dict[str, Any]", parsed)
    return {}
