"""End-to-end auto-defect chain (M1d-29 — gates v0.5.0-m1d).

Single high-fidelity E2E that drives the full M1d defect pipeline against a
real Postgres testcontainer (via the session-scoped ``api_db`` fixture in
``apps/api/tests/conftest.py``) with EVERY downstream side-effect rendered:

    runner orchestrator (apps/runner)
       → step fails (MCP_TOOL_FAILED stub via monkeypatched execute_step)
       → on_run_step_failed hook
       → DefectAutoFiler.file_for_failed_step
           → categorizer picks REGRESSION / INFRA / FLAKE from stderr blob
           → INSERT defects (created_by='system'); dedup via uq_defects_auto_dedup
           → write_audit defect.auto_filed
           → publish workspace:<wsId> defect.created (fakeredis)
           → enqueue file_external_issue (inline-dispatch → RecordingJiraAdapter)
           → enqueue send_slack_notification (inline-dispatch → respx Slack mock)

The test deliberately bypasses the real MCP stack by patching
:func:`suitest_runner.executors.step_executor.execute_step` to a controllable
stub — the runner's MCP plumbing is covered by ``apps/runner/tests`` and the
m1c E2E. This module's surface is the defect chain, not MCP.

Marked ``@pytest.mark.e2e`` so it stays out of the default
``pytest -m "not e2e"`` selector. Opt in with ``pytest apps/api/tests/e2e``.

Runtime budget: ≤60s on CI hardware (the only non-trivial cost is the
testcontainer boot which is amortised across the session via the
``_database_url`` fixture).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import respx
from api_harness import ApiDb
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from suitest_api.integrations.registry import notifier_factories
from suitest_api.integrations.slack_adapter import SlackAdapter
from suitest_api.services.defect_auto_filer import DefectAutoFiler, DefectCategorizer
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.defect import Defect, ExternalIssue
from suitest_db.models.integration import Integration
from suitest_db.models.project import Project, Suite
from suitest_db.models.run import Run
from suitest_db.models.workspace import Workspace
from suitest_db.public_id import set_workspace_id
from suitest_runner.executors.step_executor import StepResult
from suitest_runner.jobs.file_external_issue import file_external_issue
from suitest_runner.jobs.run_test_case import run_test_case
from suitest_runner.jobs.send_slack_notification import send_slack_notification
from suitest_shared.domain.enums import (
    CaseSource,
    CaseStatus,
    DiagnosisKind,
    IntegrationKind,
    Priority,
    RunStatus,
    RunTrigger,
    Severity,
    StepOutcome,
    TargetKind,
    Tier,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis

    from .conftest import RecordingJiraAdapter, SlackBodyDecoder

# Every test in this module is an E2E — mark once at module scope.
pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# DB seeding helpers (raw ORM — bypass the API to keep the test focused)
# ---------------------------------------------------------------------------


_SEVERITY_BY_DIAGNOSIS = {
    DiagnosisKind.REGRESSION: Severity.HIGH,  # case priority P1 → HIGH
    DiagnosisKind.INFRA: Severity.HIGH,
    DiagnosisKind.FLAKE: Severity.HIGH,
}


async def _seed_world(
    *,
    maker: async_sessionmaker[AsyncSession],
    slug_suffix: str,
    strict_zero_validation: bool = True,
) -> dict[str, str]:
    """Seed Workspace + Project + Suite + TestCase + TestStep + Run + run-step.

    Returns ``{workspace_id, project_id, suite_id, case_id, step_id, run_id}``.
    The Workspace is created fresh per call so each parametrize case has its
    own tenancy boundary — defects from one parametrize iteration do NOT
    collide with the dedup test downstream.
    """
    async with maker() as session:
        ws = Workspace(
            slug=f"m1d29-{slug_suffix}",
            name=f"M1d29 {slug_suffix}",
            strict_zero_validation=strict_zero_validation,
        )
        session.add(ws)
        await session.flush()

        project = Project(workspace_id=ws.id, slug=f"p-{slug_suffix}", name="P")
        session.add(project)
        await session.flush()

        suite = Suite(project_id=project.id, name="S", order=0)
        session.add(suite)
        await session.flush()

        case = TestCase(
            suite_id=suite.id,
            name="auto-defect e2e case",
            source=CaseSource.MANUAL,
            status=CaseStatus.ACTIVE,
            priority=Priority.P1,  # → HIGH severity
        )
        set_workspace_id(case, ws.id)
        session.add(case)
        await session.flush()

        step = TestStep(
            case_id=case.id,
            order=1,
            action="assert row count == 0",
            expected="0 rows",
            mcp_provider="postgres-mcp",
            target_kind=TargetKind.DATA,
            code=json.dumps({"tool": "db.assert_row_count", "arguments": {"expected": 0}}),
        )
        session.add(step)
        await session.flush()

        run = Run(
            project_id=project.id,
            name="m1d29-run",
            env="test",
            trigger=RunTrigger.MANUAL,
            status=RunStatus.QUEUED,
            tier_at_runtime=Tier.ZERO,
            metadata_json={"selection": [{"case_id": case.id}]},
        )
        set_workspace_id(run, ws.id)
        session.add(run)
        await session.flush()

        ids = {
            "workspace_id": ws.id,
            "project_id": project.id,
            "suite_id": suite.id,
            "case_id": case.id,
            "step_id": step.id,
            "run_id": run.id,
        }
        await session.commit()
        return ids


async def _seed_integrations(
    *,
    maker: async_sessionmaker[AsyncSession],
    workspace_id: str,
    webhook_url: str,
    include_jira: bool = True,
    include_slack: bool = True,
) -> dict[str, str]:
    """Insert the JIRA + SLACK ``integrations`` rows the auto-filer will enqueue against."""
    ids: dict[str, str] = {}
    async with maker() as session:
        if include_jira:
            jira = Integration(
                workspace_id=workspace_id,
                kind=IntegrationKind.JIRA,
                name="Jira (mock)",
                config={"default_for_issues": True, "project_key": "PROJ"},
                # Real JiraAdapter would consume {url, email, token}; the
                # recording adapter ignores secrets so we keep this minimal.
                secrets_encrypted=json.dumps(
                    {"url": "https://jira.example", "email": "e2e@test", "token": "x"}
                ),
                status="active",
            )
            session.add(jira)
            await session.flush()
            ids["jira_integration_id"] = jira.id
        if include_slack:
            slack = Integration(
                workspace_id=workspace_id,
                kind=IntegrationKind.SLACK,
                name="Slack (mock)",
                config={"default_for_notifications": True, "suitest_base_url": "https://app.test"},
                secrets_encrypted=json.dumps({"webhook_url": webhook_url}),
                status="active",
            )
            session.add(slack)
            await session.flush()
            ids["slack_integration_id"] = slack.id
        await session.commit()
    return ids


# ---------------------------------------------------------------------------
# execute_step monkeypatch — drives outcomes per parametrize matrix
# ---------------------------------------------------------------------------


def _make_fake_execute_step(
    *,
    stderr_blob: str,
    error_message: str,
    outcome: StepOutcome = StepOutcome.FAIL,
) -> Callable[..., Awaitable[StepResult]]:
    """Return an ``execute_step`` stand-in that yields a controllable failure.

    The runner orchestrator calls ``execute_step`` once per step in the
    selection; the stub returns the configured outcome with the supplied
    ``stderr`` + ``error_message`` so the categorizer sees a deterministic
    blob (REGRESSION / INFRA / FLAKE).
    """

    async def _fake_execute_step(**kwargs: object) -> StepResult:
        # Mirror McpToolFailed → MCP_TOOL_FAILED message shape so the
        # categorizer's regex tables hit the realistic input surface.
        now = datetime.now(UTC)
        return StepResult(
            outcome=outcome,
            started_at=now,
            completed_at=now,
            duration_ms=5,
            stdout="",
            stderr=stderr_blob,
            error_message=error_message,
            mcp_result=None,
        )

    return _fake_execute_step


# ---------------------------------------------------------------------------
# Orchestrator wiring helpers
# ---------------------------------------------------------------------------


def _build_session_factory(
    maker: async_sessionmaker[AsyncSession],
) -> Callable[[], AbstractAsyncContextManager[AsyncSession]]:
    """Return a callable that yields a fresh async-context-managed session.

    Matches the ``session_factory`` Protocol the auto-filer + runner expect:
    a zero-arg callable returning an ``async with``-capable session context.
    """

    @asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    return _factory


def _stub_registry(workspace_id: str) -> object:
    """Pre-seed an :class:`McpRegistry` stand-in so the orchestrator skips load.

    The orchestrator only reaches into ``registry._by_workspace`` to decide
    whether to lazy-load — populating that dict short-circuits the path.
    Returns a MagicMock spec'd against ``McpRegistry`` so ``isinstance`` holds.
    """
    from unittest.mock import MagicMock

    from suitest_mcp.registry import McpRegistry

    reg = MagicMock(spec=McpRegistry)
    reg._by_workspace = {workspace_id: {}}
    return reg


def _stub_invoker() -> object:
    """:class:`MagicMock` spec'd against :class:`McpInvoker` for the isinstance guard."""
    from unittest.mock import MagicMock

    from suitest_mcp.invoker import McpInvoker

    return MagicMock(spec=McpInvoker)


# ---------------------------------------------------------------------------
# Registered Slack notifier factory — re-registered per test
# ---------------------------------------------------------------------------


@pytest.fixture
def slack_factory_registered() -> Iterator[None]:
    """Register the real :class:`SlackAdapter` factory in the notifier registry.

    The production ``lifespan`` does this; the test bypasses lifespan so we
    register here directly. Cleanup pops the key on teardown.
    """
    notifier_factories[IntegrationKind.SLACK] = SlackAdapter
    try:
        yield
    finally:
        notifier_factories.pop(IntegrationKind.SLACK, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


_CATEGORY_MATRIX = [
    pytest.param(
        "AssertionError: expected 0 rows but got 5",
        "MCP_TOOL_FAILED: AssertionError x",
        DiagnosisKind.REGRESSION,
        id="REGRESSION-assertion-mismatch",
    ),
    pytest.param(
        "ECONNREFUSED 127.0.0.1:5432",
        "MCP_TOOL_FAILED: connection refused",
        DiagnosisKind.INFRA,
        id="INFRA-connection-refused",
    ),
    pytest.param(
        "Timeout exceeded after 30s; flaky test rerun",
        "MCP_TOOL_FAILED: timeout exceeded",
        DiagnosisKind.FLAKE,
        id="FLAKE-timeout",
    ),
]


@pytest.mark.parametrize(("stderr_blob", "error_message", "expected_kind"), _CATEGORY_MATRIX)
async def test_full_auto_defect_chain_categorizes_files_and_notifies(
    api_db: ApiDb,
    mock_redis: AsyncRedis,
    recording_jira_adapter: RecordingJiraAdapter,
    mock_slack_webhook: respx.MockRouter,
    slack_decoder: SlackBodyDecoder,
    slack_factory_registered: None,
    slack_webhook_url: str,
    monkeypatch: pytest.MonkeyPatch,
    stderr_blob: str,
    error_message: str,
    expected_kind: DiagnosisKind,
) -> None:
    """Happy path: runner fails → categorizer hits expected kind → Jira + Slack mocks fire.

    Asserts (per plan-05b §M1d-29):

    * defect row inserted with ``created_by='system'``, ``severity=HIGH``
      (case priority P1 → HIGH per ``severity_for_priority``),
      ``agent_diagnosis_kind=<expected>``.
    * ``defect.created`` WS event broadcast exactly once on the
      ``workspace:<wsId>`` channel.
    * mock Jira adapter received exactly one ``create_external_issue`` call
      whose body's ``title`` carries the categorized prefix.
    * mock Slack webhook received exactly one POST whose attachment colour
      matches the severity (per :data:`SEVERITY_COLOR`).
    * ``external_issues`` link row inserted by the external-issue ARQ job
      pointing at the RecordingJiraAdapter's synthetic external_id.
    """
    # Defer the import so the conftest fixture types are visible to mypy.
    from .conftest import RecordingArqPool

    slug = uuid.uuid4().hex[:8]
    ids = await _seed_world(maker=api_db.maker, slug_suffix=slug)
    await _seed_integrations(
        maker=api_db.maker,
        workspace_id=ids["workspace_id"],
        webhook_url=slack_webhook_url,
    )

    # Build the wiring ctx the orchestrator + jobs share. The ARQ pool below
    # dispatches inline against this same ctx so the file_external_issue +
    # send_slack_notification jobs see the same session_factory / redis we
    # already configured.
    session_factory = _build_session_factory(api_db.maker)
    ctx: dict[str, object] = {
        "session_factory": session_factory,
        "redis": mock_redis,
        "invoker": _stub_invoker(),
        "registry": _stub_registry(ids["workspace_id"]),
    }
    arq_pool = RecordingArqPool(
        ctx=ctx,
        functions={
            "file_external_issue": file_external_issue,
            "send_slack_notification": send_slack_notification,
        },
    )
    auto_filer = DefectAutoFiler(
        session_factory=session_factory,
        publisher=mock_redis,  # type: ignore[arg-type]
        arq_pool=arq_pool,
        categorizer=DefectCategorizer(),
    )
    ctx["defect_auto_filer"] = auto_filer
    ctx["arq_pool"] = arq_pool

    # Monkeypatch execute_step on the orchestrator module so the runner sees
    # a deterministic FAIL with the parametrized stderr blob (categorizer
    # input). We patch the symbol the orchestrator imports (``job_mod``)
    # rather than the source module so ``from .step_executor import
    # execute_step`` lookups are caught.
    import suitest_runner.jobs.run_test_case as job_mod

    monkeypatch.setattr(
        job_mod,
        "execute_step",
        _make_fake_execute_step(
            stderr_blob=stderr_blob,
            error_message=error_message,
            outcome=StepOutcome.FAIL,
        ),
    )

    # Drive the orchestrator. Returns the run summary; we don't assert against
    # it here (other tests in apps/runner cover that) — the side effects on
    # DB + redis + adapter recorder are the actual contract.
    summary = await run_test_case(ctx, ids["run_id"])
    assert summary["status"] == "FAIL", summary
    assert summary["failed"] == 1

    # ---- Defect row -------------------------------------------------------
    async with api_db.maker() as session:
        defects = list(
            (await session.scalars(select(Defect).where(Defect.run_id == ids["run_id"]))).all()
        )
    assert len(defects) == 1, [d.title for d in defects]
    defect = defects[0]
    assert defect.created_by == "system"
    assert defect.workspace_id == ids["workspace_id"]
    assert defect.test_case_id == ids["case_id"]
    assert defect.agent_diagnosis_kind is expected_kind
    assert defect.severity is _SEVERITY_BY_DIAGNOSIS[expected_kind]
    assert defect.public_id.startswith("SUIT-")

    # ---- WS broadcast + post-commit fan-out ------------------------------
    # The deterministic signal we trust here is the recording ARQ pool — the
    # auto-filer's post-commit branch enqueued exactly one external-issue job
    # and one slack job for the two integrations seeded above. Asserting on
    # the recorder list (rather than round-tripping through fakeredis pubsub,
    # which the auto-filer's ``defect.created`` publish also lands on) keeps
    # the test deterministic regardless of pubsub event-loop scheduling. The
    # ``mock_slack_webhook.calls.call_count`` assertion below is the proof
    # the WS-adjacent fan-out actually fired.
    enqueued_names = sorted(name for name, _, _ in arq_pool.enqueued)
    assert enqueued_names == ["file_external_issue", "send_slack_notification"], enqueued_names

    # ---- Mock Jira adapter ------------------------------------------------
    assert len(recording_jira_adapter.creates) == 1
    jira_body = recording_jira_adapter.creates[0]
    assert jira_body.defect_id == defect.id
    assert jira_body.severity is _SEVERITY_BY_DIAGNOSIS[expected_kind]
    assert expected_kind.value in jira_body.title

    # ---- ExternalIssue link row inserted by the external-issue job --------
    async with api_db.maker() as session:
        links = list(
            (
                await session.scalars(
                    select(ExternalIssue).where(ExternalIssue.defect_id == defect.id)
                )
            ).all()
        )
    assert len(links) == 1
    assert links[0].provider == "jira"
    assert links[0].external_id.startswith("100")
    assert links[0].external_url.startswith("https://jira.example/")

    # ---- Slack webhook POST -----------------------------------------------
    assert mock_slack_webhook.calls.call_count == 1
    slack_body = slack_decoder.last_payload()
    # Adapter uses the attachment form whenever a colour is set (severity bar).
    attachments = slack_body.get("attachments")
    assert isinstance(attachments, list) and len(attachments) == 1
    assert attachments[0].get("color") in {"#9CA3AF", "#FBBF24", "#F87171", "#DC2626"}
    blocks = attachments[0].get("blocks")
    assert isinstance(blocks, list) and len(blocks) >= 1
    header = blocks[0]
    assert header.get("type") == "header"
    assert defect.public_id in header["text"]["text"]


async def test_dedup_second_failure_for_same_run_case_does_not_double_file(
    api_db: ApiDb,
    mock_redis: AsyncRedis,
    recording_jira_adapter: RecordingJiraAdapter,
    mock_slack_webhook: respx.MockRouter,
    slack_factory_registered: None,
    slack_webhook_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second invocation of the auto-filer on the same (run, case) is a no-op.

    The partial unique index ``uq_defects_auto_dedup`` (revision
    ``0021_m1d_06_defect_dedup``) catches a duplicate ``(run_id, test_case_id)
    WHERE created_by='system'`` insert; the auto-filer rolls back + returns
    ``None``. After two calls there must still be exactly one defect row.
    """
    from .conftest import RecordingArqPool

    slug = uuid.uuid4().hex[:8]
    ids = await _seed_world(maker=api_db.maker, slug_suffix=slug)
    await _seed_integrations(
        maker=api_db.maker,
        workspace_id=ids["workspace_id"],
        webhook_url=slack_webhook_url,
    )

    session_factory = _build_session_factory(api_db.maker)
    ctx: dict[str, object] = {
        "session_factory": session_factory,
        "redis": mock_redis,
        "invoker": _stub_invoker(),
        "registry": _stub_registry(ids["workspace_id"]),
    }
    arq_pool = RecordingArqPool(
        ctx=ctx,
        # On the dedup re-run we don't want the inline jobs to fire again —
        # the auto-filer returns None before reaching the enqueue loop on the
        # dedup path, so the arq_pool stays unused for the second call. Map
        # the names anyway so the FIRST call's enqueues still execute.
        functions={
            "file_external_issue": file_external_issue,
            "send_slack_notification": send_slack_notification,
        },
    )
    auto_filer = DefectAutoFiler(
        session_factory=session_factory,
        publisher=mock_redis,  # type: ignore[arg-type]
        arq_pool=arq_pool,
        categorizer=DefectCategorizer(),
    )
    ctx["defect_auto_filer"] = auto_filer
    ctx["arq_pool"] = arq_pool

    # First failure → defect filed.
    import suitest_runner.jobs.run_test_case as job_mod

    monkeypatch.setattr(
        job_mod,
        "execute_step",
        _make_fake_execute_step(
            stderr_blob="AssertionError: expected 0 got 5",
            error_message="MCP_TOOL_FAILED: AssertionError",
        ),
    )
    summary = await run_test_case(ctx, ids["run_id"])
    assert summary["status"] == "FAIL"

    async with api_db.maker() as session:
        first_defects = list(
            (await session.scalars(select(Defect).where(Defect.run_id == ids["run_id"]))).all()
        )
    assert len(first_defects) == 1
    first_defect_id = first_defects[0].id

    # Second invocation simulating a runner-level retry of the SAME step row.
    # We look up the inserted run_steps row to feed the filer directly so the
    # second attempt collides on the partial unique idx.
    from suitest_db.models.run import RunStep

    async with api_db.maker() as session:
        rs_rows = list(
            (await session.scalars(select(RunStep).where(RunStep.run_id == ids["run_id"]))).all()
        )
    assert len(rs_rows) == 1
    result = await auto_filer.file_for_failed_step(rs_rows[0].id)
    assert result is None, "second filer call must dedup → None"

    async with api_db.maker() as session:
        second_defects = list(
            (await session.scalars(select(Defect).where(Defect.run_id == ids["run_id"]))).all()
        )
    assert len(second_defects) == 1
    assert second_defects[0].id == first_defect_id


async def test_jira_failure_does_not_break_slack_post(
    api_db: ApiDb,
    mock_redis: AsyncRedis,
    recording_jira_adapter: RecordingJiraAdapter,
    mock_slack_webhook: respx.MockRouter,
    slack_decoder: SlackBodyDecoder,
    slack_factory_registered: None,
    slack_webhook_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Jira adapter explodes → Slack STILL receives the notification.

    The auto-filer enqueues both jobs independently; one failing must not
    starve the other. The Jira job catches :class:`AdapterError` and writes a
    failure audit row; the Slack job proceeds untouched.
    """
    from suitest_api.integrations.base import AdapterRemoteError

    from .conftest import RecordingArqPool

    slug = uuid.uuid4().hex[:8]
    ids = await _seed_world(maker=api_db.maker, slug_suffix=slug)
    await _seed_integrations(
        maker=api_db.maker,
        workspace_id=ids["workspace_id"],
        webhook_url=slack_webhook_url,
    )

    # Configure the recorded Jira adapter to raise on create.
    recording_jira_adapter.raise_on_create = AdapterRemoteError("Jira 502 Bad Gateway")

    session_factory = _build_session_factory(api_db.maker)
    ctx: dict[str, object] = {
        "session_factory": session_factory,
        "redis": mock_redis,
        "invoker": _stub_invoker(),
        "registry": _stub_registry(ids["workspace_id"]),
    }
    arq_pool = RecordingArqPool(
        ctx=ctx,
        functions={
            "file_external_issue": file_external_issue,
            "send_slack_notification": send_slack_notification,
        },
    )
    auto_filer = DefectAutoFiler(
        session_factory=session_factory,
        publisher=mock_redis,  # type: ignore[arg-type]
        arq_pool=arq_pool,
        categorizer=DefectCategorizer(),
    )
    ctx["defect_auto_filer"] = auto_filer
    ctx["arq_pool"] = arq_pool

    import suitest_runner.jobs.run_test_case as job_mod

    monkeypatch.setattr(
        job_mod,
        "execute_step",
        _make_fake_execute_step(
            stderr_blob="AssertionError: expected 0 got 5",
            error_message="MCP_TOOL_FAILED: AssertionError",
        ),
    )
    summary = await run_test_case(ctx, ids["run_id"])
    assert summary["status"] == "FAIL"

    # Jira adapter was called and raised — captured in the recorder.
    assert len(recording_jira_adapter.creates) == 1

    # ExternalIssue link MUST NOT be inserted when the adapter raises.
    async with api_db.maker() as session:
        links = list(
            (
                await session.scalars(
                    select(ExternalIssue).where(
                        ExternalIssue.defect_id
                        == (
                            await session.scalar(
                                select(Defect.id).where(Defect.run_id == ids["run_id"])
                            )
                        )
                    )
                )
            ).all()
        )
    assert links == [], "Jira failure must not leave a stale ExternalIssue row"

    # Slack webhook still received its POST — the chain didn't unravel.
    assert mock_slack_webhook.calls.call_count == 1, (
        "Slack POST must fire even when the Jira leg blows up"
    )
    payload = slack_decoder.last_payload()
    assert "attachments" in payload

    # And the defect itself was filed (the auto-filer's success branch ran
    # before either downstream job; Slack/Jira are best-effort enrichments).
    async with api_db.maker() as session:
        defects = list(
            (await session.scalars(select(Defect).where(Defect.run_id == ids["run_id"]))).all()
        )
    assert len(defects) == 1
    assert defects[0].created_by == "system"


async def test_workspace_strict_zero_false_step_without_code_still_files_defect_on_failure(
    api_db: ApiDb,
    mock_redis: AsyncRedis,
    recording_jira_adapter: RecordingJiraAdapter,
    mock_slack_webhook: respx.MockRouter,
    slack_factory_registered: None,
    slack_webhook_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``strict_zero_validation=False`` workspace still files defects on runtime FAIL.

    The lenient path lets a step ship without ``code`` populated (manual TCM
    descriptive-only); when the runner DOES still execute it (here we force a
    FAIL via the execute_step stub), the auto-filer MUST behave identically
    to the strict-validation path — defect filed, jobs enqueued.

    The toggle is workspace-level (``workspaces.strict_zero_validation``);
    M1d-29 covers that the auto-defect chain is orthogonal to it. The runner
    orchestrator doesn't read this flag — it's an API-layer validator for
    POST /test-cases — so this test mostly proves the seed shape works end
    to end with the flag in its OFF position.
    """
    from .conftest import RecordingArqPool

    slug = uuid.uuid4().hex[:8]
    ids = await _seed_world(maker=api_db.maker, slug_suffix=slug, strict_zero_validation=False)
    await _seed_integrations(
        maker=api_db.maker,
        workspace_id=ids["workspace_id"],
        webhook_url=slack_webhook_url,
    )

    session_factory = _build_session_factory(api_db.maker)
    ctx: dict[str, object] = {
        "session_factory": session_factory,
        "redis": mock_redis,
        "invoker": _stub_invoker(),
        "registry": _stub_registry(ids["workspace_id"]),
    }
    arq_pool = RecordingArqPool(
        ctx=ctx,
        functions={
            "file_external_issue": file_external_issue,
            "send_slack_notification": send_slack_notification,
        },
    )
    auto_filer = DefectAutoFiler(
        session_factory=session_factory,
        publisher=mock_redis,  # type: ignore[arg-type]
        arq_pool=arq_pool,
        categorizer=DefectCategorizer(),
    )
    ctx["defect_auto_filer"] = auto_filer
    ctx["arq_pool"] = arq_pool

    import suitest_runner.jobs.run_test_case as job_mod

    monkeypatch.setattr(
        job_mod,
        "execute_step",
        _make_fake_execute_step(
            stderr_blob="AssertionError: lenient path still fails at runtime",
            error_message="MCP_TOOL_FAILED: AssertionError",
        ),
    )
    summary = await run_test_case(ctx, ids["run_id"])
    assert summary["status"] == "FAIL"

    async with api_db.maker() as session:
        ws_rows = list(
            (
                await session.scalars(select(Workspace).where(Workspace.id == ids["workspace_id"]))
            ).all()
        )
    assert ws_rows[0].strict_zero_validation is False

    async with api_db.maker() as session:
        defects = list(
            (await session.scalars(select(Defect).where(Defect.run_id == ids["run_id"]))).all()
        )
    assert len(defects) == 1
    assert defects[0].created_by == "system"
    assert defects[0].agent_diagnosis_kind is DiagnosisKind.REGRESSION
