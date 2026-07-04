"""Tests for the ``dispatch_webhook`` ARQ job (M4-31).

Coverage:

* Success → ledger row ``status=succeeded``.
* Transient failure, attempt < MAX_ATTEMPTS → ``status=failed``, ``next_retry_at``
  set, re-enqueued with the correct backoff defer.
* Exhausted budget → dead-letter: ``status=dead_letter``, integration flipped to
  ``status=error``, ``integration.error`` emitted on ``workspace:<id>``.
* Auth error → immediate dead-letter (no retry).

The job's collaborators are the notifier factory registry + a fake session
factory returning shared row instances so in-place mutations persist across the
job's multiple short-lived sessions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from suitest_api.integrations.base import (
    AdapterAuthError,
    AdapterTimeoutError,
    DefectEvent,
    NotificationResult,
    NotifierAdapter,
)
from suitest_api.integrations.registry import notifier_factories
from suitest_api.services.webhook_retry_queue import BACKOFF_SECONDS, MAX_ATTEMPTS
from suitest_db.models.integration import Integration
from suitest_db.models.webhook_dispatch import WebhookDispatchAttempt
from suitest_runner.jobs.dispatch_webhook import dispatch_webhook
from suitest_shared.domain.enums import DiagnosisKind, IntegrationKind, Severity


def _make_integration() -> Integration:
    return Integration(
        id="int_slack_1",
        workspace_id="ws_1",
        kind=IntegrationKind.SLACK,
        name="Slack",
        config={"suitest_base_url": "https://app.example"},
        secrets_encrypted='{"webhook_url": "https://hooks.slack.com/x"}',
        status="active",
    )


def _make_attempt(attempt_n: int = 0) -> WebhookDispatchAttempt:
    return WebhookDispatchAttempt(
        id="wda_1",
        workspace_id="ws_1",
        integration_id="int_slack_1",
        idempotency_key="defect:defc_1:notify",
        operation="send_notification",
        payload_json={
            "defect_id": "defc_1",
            "defect_public_id": "DEF-1",
            "title": "Failing login",
            "severity": Severity.HIGH.value,
            "diagnosis_kind": DiagnosisKind.REGRESSION.value,
            "workspace_id": "ws_1",
            "suitest_base_url": "https://app.example",
        },
        payload_hash="x",
        status="pending",
        attempt_n=attempt_n,
    )


class _FakeSession:
    def __init__(self, store: dict[str, object]) -> None:
        self._store = store
        self.committed = 0
        self.added: list[object] = []

    async def get(self, model: type, id_: str) -> object | None:
        if model is WebhookDispatchAttempt:
            return self._store.get("attempt")
        if model is Integration:
            return self._store.get("integration")
        return None

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def commit(self) -> None:
        self.committed += 1

    async def flush(self) -> None:
        return None


def _factory(store: dict[str, object]) -> Callable[[], Any]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[_FakeSession]:
        yield _FakeSession(store)

    return factory


@dataclass
class _RecordingRedis:
    published: dict[str, list[str]] = field(default_factory=dict)

    async def publish(self, channel: str, message: str) -> int:
        self.published.setdefault(channel, []).append(message)
        return 1


@dataclass
class _RecordingArq:
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = field(default_factory=list)

    async def enqueue_job(self, name: str, *args: object, **kwargs: object) -> object:
        self.calls.append((name, args, kwargs))
        return object()


class _Notifier:
    kind = IntegrationKind.SLACK

    def __init__(self, *, outcome: str | type[Exception]) -> None:
        self._outcome = outcome
        self.calls: list[DefectEvent] = []

    async def test_connection(self) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def send_notification(
        self, event: DefectEvent, config: dict[str, Any], secrets: dict[str, Any]
    ) -> NotificationResult:
        self.calls.append(event)
        if isinstance(self._outcome, type):
            raise self._outcome("synthetic")
        return NotificationResult(sent=True)


@pytest.fixture()
def register_notifier() -> Iterator[Callable[[str | type[Exception]], _Notifier]]:
    def _register(outcome: str | type[Exception]) -> _Notifier:
        notifier = _Notifier(outcome=outcome)

        def _factory_callable(
            integration: Integration, http_client: httpx.AsyncClient
        ) -> NotifierAdapter:
            return notifier

        notifier_factories[IntegrationKind.SLACK] = _factory_callable
        return notifier

    yield _register


@pytest.mark.asyncio
async def test_success_marks_succeeded(
    register_notifier: Callable[[str | type[Exception]], _Notifier],
) -> None:
    register_notifier("OK")
    attempt = _make_attempt()
    store: dict[str, object] = {"attempt": attempt, "integration": _make_integration()}
    ctx = {
        "session_factory": _factory(store),
        "redis": _RecordingRedis(),
        "arq_pool": _RecordingArq(),
    }

    out = await dispatch_webhook(ctx, "wda_1")

    assert out["dispatched"] is True
    assert attempt.status == "succeeded"
    assert attempt.succeeded_at is not None


@pytest.mark.asyncio
async def test_transient_failure_reschedules_with_backoff(
    register_notifier: Callable[[str | type[Exception]], _Notifier],
) -> None:
    register_notifier(AdapterTimeoutError)
    attempt = _make_attempt(attempt_n=0)  # becomes 1 after increment
    store: dict[str, object] = {"attempt": attempt, "integration": _make_integration()}
    arq = _RecordingArq()
    ctx = {"session_factory": _factory(store), "redis": _RecordingRedis(), "arq_pool": arq}

    out = await dispatch_webhook(ctx, "wda_1")

    assert out["dispatched"] is False
    assert attempt.status == "failed"
    assert attempt.next_retry_at is not None
    # one re-enqueue with backoff defer == BACKOFF_SECONDS[0]
    assert arq.calls and arq.calls[0][0] == "dispatch_webhook"
    assert arq.calls[0][2]["_defer_by"] == BACKOFF_SECONDS[0]


@pytest.mark.asyncio
async def test_exhausted_budget_dead_letters(
    register_notifier: Callable[[str | type[Exception]], _Notifier],
) -> None:
    register_notifier(AdapterTimeoutError)
    integration = _make_integration()
    attempt = _make_attempt(attempt_n=MAX_ATTEMPTS - 1)  # becomes MAX after increment
    store: dict[str, object] = {"attempt": attempt, "integration": integration}
    redis = _RecordingRedis()
    ctx = {"session_factory": _factory(store), "redis": redis, "arq_pool": _RecordingArq()}

    out = await dispatch_webhook(ctx, "wda_1")

    assert out["dispatched"] is False
    assert attempt.status == "dead_letter"
    assert integration.status == "error"
    assert "workspace:ws_1" in redis.published
    assert "integration.error" in redis.published["workspace:ws_1"][0]


@pytest.mark.asyncio
async def test_auth_error_dead_letters_immediately(
    register_notifier: Callable[[str | type[Exception]], _Notifier],
) -> None:
    register_notifier(AdapterAuthError)
    integration = _make_integration()
    attempt = _make_attempt(attempt_n=0)  # first attempt
    store: dict[str, object] = {"attempt": attempt, "integration": integration}
    ctx = {
        "session_factory": _factory(store),
        "redis": _RecordingRedis(),
        "arq_pool": _RecordingArq(),
    }

    out = await dispatch_webhook(ctx, "wda_1")

    assert out["dispatched"] is False
    assert attempt.status == "dead_letter"
    assert integration.status == "error"
