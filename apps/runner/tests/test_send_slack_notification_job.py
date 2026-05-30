"""Tests for ``send_slack_notification`` ARQ job (M1d-15).

Coverage:

* Happy path: webhook 200 → ``{"sent": True}``.
* Transient adapter failure on attempt < max_tries → re-raises so ARQ retries.
* Terminal failure (attempt == max_tries): flips ``integration.status=error``,
  emits ``integration.error`` on ``workspace:<wsId>`` Redis channel, returns
  ``{"sent": False, "error": ...}`` (caller swallows so worker doesn't loop).
* Job exits early when integration / defect rows are missing.

The job's only external collaborator is the adapter factory it resolves from
:data:`notifier_factory_registry`; we register a fake factory per test so the
tests stay fast and don't need a real httpx + Slack mock.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from suitest_api.integrations.base import (
    AdapterError,
    AdapterRemoteError,
    AdapterTimeoutError,
    DefectEvent,
    NotificationResult,
    NotifierAdapter,
)
from suitest_api.integrations.notifier_registry import (
    NotifierFactoryRegistry,
    notifier_factory_registry,
)
from suitest_db.models.defect import Defect
from suitest_db.models.integration import Integration
from suitest_runner.jobs.send_slack_notification import (
    JOB_MAX_TRIES,
    send_slack_notification,
)
from suitest_shared.domain.enums import DefectStatus, DiagnosisKind, IntegrationKind, Severity

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _make_integration() -> Integration:
    integration = Integration(
        id="int_slack_1",
        workspace_id="ws_1",
        kind=IntegrationKind.SLACK,
        name="Slack",
        config={"suitest_base_url": "https://app.example"},
        secrets_encrypted=json.dumps({"webhook_url": "https://hooks.slack.com/services/T/B/X"}),
        status="active",
    )
    return integration


def _make_defect() -> Defect:
    defect = Defect(
        id="defc_1",
        public_id="DEF-1",
        workspace_id="ws_1",
        title="Failing login",
        severity=Severity.HIGH,
        status=DefectStatus.OPEN,
        run_id="run_1",
        agent_diagnosis_kind=DiagnosisKind.REGRESSION,
        created_by="user-1",
    )
    return defect


class _FakeSession:
    """In-memory session stub satisfying the job's tiny session surface."""

    def __init__(self, integration: Integration | None, defect: Defect | None) -> None:
        self._integration = integration
        self._defect = defect
        self.added: list[object] = []
        self.committed = False

    async def get(self, model: type, id_: str) -> object | None:
        if model is Defect:
            return self._defect
        if model is Integration:
            return self._integration
        return None

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def commit(self) -> None:
        self.committed = True

    async def flush(self) -> None:
        return None


def _session_factory(
    integration: Integration | None,
    defect: Defect | None,
) -> Callable[[], Any]:
    """Mimic ``async_sessionmaker`` — a callable returning an async-ctx session."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[_FakeSession]:
        yield _FakeSession(integration, defect)

    return factory


@dataclass
class _RecordingRedis:
    published: dict[str, list[str]] = field(default_factory=dict)

    async def publish(self, channel: str, message: str) -> int:
        self.published.setdefault(channel, []).append(message)
        return 1


class _FakeAdapter:
    """Deterministic NotifierAdapter stand-in driven by a list of outcomes."""

    kind = IntegrationKind.SLACK

    def __init__(
        self,
        *,
        outcomes: list[str | type[Exception]],
    ) -> None:
        self._outcomes = outcomes
        self._i = 0
        self.calls: list[DefectEvent] = []

    async def test_connection(self) -> Any:  # pragma: no cover — unused in this suite
        raise NotImplementedError

    async def send_notification(
        self,
        event: DefectEvent,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> NotificationResult:
        self.calls.append(event)
        idx = min(self._i, len(self._outcomes) - 1)
        outcome = self._outcomes[idx]
        self._i += 1
        if isinstance(outcome, type) and issubclass(outcome, Exception):
            raise outcome("synthetic")
        if outcome == "OK":
            return NotificationResult(sent=True)
        if outcome == "RETURN_FAILED":
            return NotificationResult(sent=False, error="adapter returned False")
        raise AssertionError(f"unknown outcome {outcome!r}")


# Confirm the Protocol membership at type-check time so test stubs don't
# silently drift away from the adapter contract.
def _confirm_fake_adapter_is_protocol() -> None:
    fake: NotifierAdapter = _FakeAdapter(outcomes=["OK"])
    assert fake.kind is IntegrationKind.SLACK


@pytest.fixture()
def _isolate_registry() -> Iterator[NotifierFactoryRegistry]:
    """Replace the module-global registry contents for each test.

    The job resolves the factory off the singleton; tests register a fake
    factory per case. Resetting the dict on teardown so a later test doesn't
    inherit a stale factory.
    """
    original = dict(notifier_factory_registry._by_kind)
    notifier_factory_registry._by_kind.clear()
    yield notifier_factory_registry
    notifier_factory_registry._by_kind.clear()
    notifier_factory_registry._by_kind.update(original)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_returns_sent_true(
    _isolate_registry: NotifierFactoryRegistry,
) -> None:
    integration = _make_integration()
    defect = _make_defect()
    adapter = _FakeAdapter(outcomes=["OK"])
    _isolate_registry.register(IntegrationKind.SLACK, lambda _i, _h: adapter)

    ctx = {
        "session_factory": _session_factory(integration, defect),
        "redis": _RecordingRedis(),
        "job_try": 1,
    }
    result = await send_slack_notification(ctx, "int_slack_1", "defc_1")
    assert result == {"sent": True}
    # Adapter received the projected DefectEvent.
    assert len(adapter.calls) == 1
    assert adapter.calls[0].defect_public_id == "DEF-1"
    assert adapter.calls[0].severity is Severity.HIGH


# ---------------------------------------------------------------------------
# Missing rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_integration_returns_not_found(
    _isolate_registry: NotifierFactoryRegistry,
) -> None:
    _isolate_registry.register(IntegrationKind.SLACK, lambda _i, _h: _FakeAdapter(outcomes=["OK"]))
    ctx = {
        "session_factory": _session_factory(None, _make_defect()),
        "redis": _RecordingRedis(),
        "job_try": 1,
    }
    result = await send_slack_notification(ctx, "int_missing", "defc_1")
    assert result == {"sent": False, "error": "INTEGRATION_NOT_FOUND"}


@pytest.mark.asyncio
async def test_missing_defect_returns_not_found(
    _isolate_registry: NotifierFactoryRegistry,
) -> None:
    _isolate_registry.register(IntegrationKind.SLACK, lambda _i, _h: _FakeAdapter(outcomes=["OK"]))
    ctx = {
        "session_factory": _session_factory(_make_integration(), None),
        "redis": _RecordingRedis(),
        "job_try": 1,
    }
    result = await send_slack_notification(ctx, "int_slack_1", "missing")
    assert result == {"sent": False, "error": "DEFECT_NOT_FOUND"}


@pytest.mark.asyncio
async def test_wrong_kind_returns_mismatch(
    _isolate_registry: NotifierFactoryRegistry,
) -> None:
    integration = _make_integration()
    integration.kind = IntegrationKind.JIRA
    _isolate_registry.register(IntegrationKind.SLACK, lambda _i, _h: _FakeAdapter(outcomes=["OK"]))
    ctx = {
        "session_factory": _session_factory(integration, _make_defect()),
        "redis": _RecordingRedis(),
        "job_try": 1,
    }
    result = await send_slack_notification(ctx, "int_slack_1", "defc_1")
    assert result == {"sent": False, "error": "INTEGRATION_KIND_MISMATCH"}


# ---------------------------------------------------------------------------
# Retry on transient failure (attempt < max_tries → re-raise so ARQ retries)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transient_remote_error_reraises_for_arq_retry(
    _isolate_registry: NotifierFactoryRegistry,
) -> None:
    integration = _make_integration()
    defect = _make_defect()
    _isolate_registry.register(
        IntegrationKind.SLACK,
        lambda _i, _h: _FakeAdapter(outcomes=[AdapterRemoteError]),
    )
    ctx = {
        "session_factory": _session_factory(integration, defect),
        "redis": _RecordingRedis(),
        "job_try": 1,  # first attempt — ARQ should get the exception
    }
    with pytest.raises(AdapterRemoteError):
        await send_slack_notification(ctx, "int_slack_1", "defc_1")
    # Status untouched on transient failures (only flipped on terminal).
    assert integration.status == "active"


@pytest.mark.asyncio
async def test_transient_timeout_reraises_for_arq_retry(
    _isolate_registry: NotifierFactoryRegistry,
) -> None:
    _isolate_registry.register(
        IntegrationKind.SLACK,
        lambda _i, _h: _FakeAdapter(outcomes=[AdapterTimeoutError]),
    )
    integration = _make_integration()
    defect = _make_defect()
    ctx = {
        "session_factory": _session_factory(integration, defect),
        "redis": _RecordingRedis(),
        "job_try": 3,  # mid-flight retry
    }
    with pytest.raises(AdapterTimeoutError):
        await send_slack_notification(ctx, "int_slack_1", "defc_1")


@pytest.mark.asyncio
async def test_adapter_returned_failed_reraises_until_terminal(
    _isolate_registry: NotifierFactoryRegistry,
) -> None:
    """Adapter returns ``sent=False`` (no raise) → treated as transient, re-raised."""
    _isolate_registry.register(
        IntegrationKind.SLACK,
        lambda _i, _h: _FakeAdapter(outcomes=["RETURN_FAILED"]),
    )
    integration = _make_integration()
    defect = _make_defect()
    ctx = {
        "session_factory": _session_factory(integration, defect),
        "redis": _RecordingRedis(),
        "job_try": 1,
    }
    with pytest.raises(AdapterError):
        await send_slack_notification(ctx, "int_slack_1", "defc_1")


# ---------------------------------------------------------------------------
# Terminal failure (attempt == max_tries → return + side-effects)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminal_failure_marks_integration_error_and_broadcasts(
    _isolate_registry: NotifierFactoryRegistry,
) -> None:
    integration = _make_integration()
    defect = _make_defect()
    _isolate_registry.register(
        IntegrationKind.SLACK,
        lambda _i, _h: _FakeAdapter(outcomes=[AdapterRemoteError]),
    )
    redis = _RecordingRedis()
    ctx = {
        "session_factory": _session_factory(integration, defect),
        "redis": redis,
        "job_try": JOB_MAX_TRIES,  # last permissible attempt — terminal
    }
    result = await send_slack_notification(ctx, "int_slack_1", "defc_1")

    assert result["sent"] is False
    assert isinstance(result["error"], str) and "synthetic" in result["error"]
    # Integration row flipped to ``error``.
    assert integration.status == "error"
    # WS broadcast hit the workspace:<wsId> channel.
    messages = redis.published.get("workspace:ws_1", [])
    assert len(messages) == 1
    payload = json.loads(messages[0])
    assert payload["event"] == "integration.error"
    assert payload["data"]["integrationId"] == "int_slack_1"
    assert payload["data"]["kind"] == "SLACK"
    assert payload["data"]["defectId"] == "defc_1"


@pytest.mark.asyncio
async def test_terminal_failure_for_adapter_returned_failed_marks_error(
    _isolate_registry: NotifierFactoryRegistry,
) -> None:
    """Adapter returns ``sent=False`` on the last attempt → terminal handling kicks in."""
    integration = _make_integration()
    defect = _make_defect()
    _isolate_registry.register(
        IntegrationKind.SLACK,
        lambda _i, _h: _FakeAdapter(outcomes=["RETURN_FAILED"]),
    )
    redis = _RecordingRedis()
    ctx = {
        "session_factory": _session_factory(integration, defect),
        "redis": redis,
        "job_try": JOB_MAX_TRIES,
    }
    result = await send_slack_notification(ctx, "int_slack_1", "defc_1")
    assert result["sent"] is False
    assert integration.status == "error"
    assert "workspace:ws_1" in redis.published
