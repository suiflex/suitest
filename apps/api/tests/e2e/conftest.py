"""E2E-scoped fixtures for :mod:`apps.api.tests.e2e.test_auto_defect_e2e` (M1d-29).

Reuses the session-scoped pgvector testcontainer + Alembic-applied-to-head
DB from :mod:`apps.api.tests.conftest` (via the ``_database_url`` /
``api_db`` fixtures). The per-test fixture set below layers on the M1d-29
specific machinery:

* ``mock_redis`` — :mod:`fakeredis.aioredis.FakeRedis` instance shared by the
  orchestrator publisher AND the runner ARQ-job side effects (each job uses
  ``redis_client.publish`` to fan out ``integration.error`` events).
* ``sync_arq_pool`` — a recording ARQ pool stub whose ``enqueue_job`` does NOT
  go through a real ARQ broker; instead it dispatches the named job function
  inline with the ctx the test already wired. Lets us assert side effects
  (Jira adapter called, Slack httpx mock hit) without running an ARQ worker.
* ``mock_slack_webhook`` — :mod:`respx` route that intercepts the Slack
  webhook POST and returns 200; captures the request bodies for assertion.
* ``recording_jira_adapter`` — fake :class:`IssueTrackerAdapter` registered in
  the process-wide :data:`adapter_registry` so the
  :func:`file_external_issue` ARQ job resolves it (no real ``jirac-mcp``
  binary on the CI image). The adapter records every
  ``create_external_issue`` call so the test can assert the categorized
  defect payload reached "Jira".

Fixtures are intentionally function-scoped (apart from ``_database_url``)
because the auto-defect chain mutates global registries (adapter +
notifier_factory) and we don't want one parametrized case leaking state into
the next.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import pytest_asyncio
import respx
from fakeredis import aioredis as fake_aioredis
from redis.asyncio import Redis as AsyncRedis
from suitest_api.integrations.base import (
    ConnectionTestResult,
    ExternalIssue,
    ExternalIssueInput,
)
from suitest_api.integrations.registry import adapter_registry
from suitest_shared.domain.enums import DefectStatus, IntegrationKind

# ---------------------------------------------------------------------------
# Recording ARQ pool — dispatches enqueued jobs inline
# ---------------------------------------------------------------------------


JobFn = Callable[..., Awaitable[dict[str, object]]]


@dataclass
class RecordingArqPool:
    """ARQ-pool stand-in that runs enqueued jobs inline against a shared ctx.

    The auto-filer + Slack/external-issue jobs collaborate through ARQ in
    production. For the E2E we want to assert the WHOLE chain (defect filed →
    Slack POSTed → Jira called) without a real ARQ worker. The pool below
    records every ``enqueue_job`` invocation and **immediately** executes the
    named function with the same ``ctx`` dict the orchestrator is using; that
    way the jobs see the real session_factory / redis / adapter registry.

    Args:
        ctx: The job-runtime context the inline-dispatched functions receive.
            Caller mutates this dict before invoking the orchestrator so the
            jobs see ``session_factory``, ``redis``, etc.
        functions: Map of job-name → coroutine. Jobs not registered here are
            recorded but NOT executed (used to assert the auto-filer enqueues
            the expected names without actually firing the side-effect).
    """

    ctx: dict[str, object]
    functions: dict[str, JobFn]
    enqueued: list[tuple[str, tuple[object, ...], dict[str, object]]] = field(default_factory=list)
    results: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    async def enqueue_job(self, name: str, *args: object, **kwargs: object) -> object:
        """Record then inline-execute the job. Returns a tiny stand-in handle."""
        self.enqueued.append((name, args, kwargs))
        fn = self.functions.get(name)
        if fn is None:
            return _RecordingJob(job_id=f"unrun-{len(self.enqueued)}")
        # ARQ injects ``job_try`` for retry-aware jobs; we always pass 1 so
        # the terminal-attempt branch never fires in the inline harness.
        local_ctx = dict(self.ctx)
        local_ctx.setdefault("job_try", 1)
        result = await fn(local_ctx, *args, **kwargs)
        self.results.append((name, result))
        return _RecordingJob(job_id=f"job-{len(self.enqueued)}")


@dataclass
class _RecordingJob:
    """Minimal :class:`arq.jobs.Job` stand-in carrying just the id."""

    job_id: str


# ---------------------------------------------------------------------------
# Recording Jira adapter
# ---------------------------------------------------------------------------


@dataclass
class RecordingJiraAdapter:
    """Fake :class:`IssueTrackerAdapter` for the JIRA integration kind.

    The real M1d-12 ``JiraAdapter`` delegates to the bundled ``jirac-mcp``
    binary; bundling that binary in CI is out of scope for M1d-29. The
    recorder below satisfies the :class:`IssueTrackerAdapter` Protocol and
    captures every call to ``create_external_issue`` so the E2E can assert
    the categorized REGRESSION defect made it across the wire.
    """

    kind: IntegrationKind = IntegrationKind.JIRA
    creates: list[ExternalIssueInput] = field(default_factory=list)
    raise_on_create: Exception | None = None

    async def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=True, display_name="Recording Jira")

    async def create_external_issue(self, body: ExternalIssueInput) -> ExternalIssue:
        self.creates.append(body)
        if self.raise_on_create is not None:
            raise self.raise_on_create
        idx = len(self.creates)
        return ExternalIssue(
            external_id=f"100{idx}",
            external_key=f"PROJ-{idx}",
            external_url=f"https://jira.example/browse/PROJ-{idx}",
            external_status="To Do",
            raw_payload={"key": f"PROJ-{idx}", "id": f"100{idx}"},
        )

    async def update_external_issue(
        self, external_key: str, body: ExternalIssueInput
    ) -> ExternalIssue:
        # Unused by the auto-defect chain — provided for Protocol completeness.
        return ExternalIssue(
            external_id="0",
            external_key=external_key,
            external_url=f"https://jira.example/browse/{external_key}",
            external_status="To Do",
            raw_payload={},
        )

    async def transition_status(self, external_key: str, new_status: DefectStatus) -> None:
        return None

    def map_external_status_to_defect_status(self, external_status: str) -> DefectStatus | None:
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def mock_redis() -> AsyncIterator[AsyncRedis]:
    """Per-test :class:`fakeredis.aioredis.FakeRedis` for publisher + jobs."""
    client = fake_aioredis.FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def recording_jira_adapter() -> Iterator[RecordingJiraAdapter]:
    """Register a fake Jira adapter in the process-wide registry for the test.

    The adapter is unregistered on teardown so a subsequent test doesn't see
    a leaked recorder (the registry is a module-level singleton).
    """
    adapter = RecordingJiraAdapter()
    adapter_registry.register(adapter)
    try:
        yield adapter
    finally:
        adapter_registry._by_kind.pop(IntegrationKind.JIRA, None)


@pytest.fixture
def slack_webhook_url() -> str:
    """Canonical Slack webhook URL the mock intercepts."""
    return "https://hooks.slack.com/services/T_TEST/B_TEST/SECRET"


@pytest.fixture
def mock_slack_webhook(slack_webhook_url: str) -> Iterator[respx.MockRouter]:
    """Intercept POSTs to the Slack webhook URL; assert the body shape in tests."""
    with respx.mock(assert_all_called=False) as router:
        router.post(slack_webhook_url).mock(
            return_value=httpx.Response(200, text="ok"),
        )
        yield router


@dataclass
class SlackBodyDecoder:
    """Tiny helper for tests: parse the most recent POSTed Slack body to dict."""

    router: respx.MockRouter

    def last_payload(self) -> dict[str, Any]:
        calls = self.router.calls
        if not calls:
            raise AssertionError("no Slack webhook calls recorded")
        request = calls[-1].request
        body = request.content
        if isinstance(body, (bytes, bytearray)):
            decoded = json.loads(body.decode())
        else:
            decoded = json.loads(body)
        if not isinstance(decoded, dict):
            raise AssertionError(f"expected JSON object body, got {type(decoded).__name__}")
        return decoded


@pytest.fixture
def slack_decoder(mock_slack_webhook: respx.MockRouter) -> SlackBodyDecoder:
    """Convenience wrapper to inspect the most recent Slack POST."""
    return SlackBodyDecoder(router=mock_slack_webhook)
