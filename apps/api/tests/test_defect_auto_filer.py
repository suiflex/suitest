"""Tests for :mod:`suitest_api.services.defect_auto_filer` (M1d-10).

Coverage matrix:

* :class:`DefectCategorizer` — one test per ``_RULES`` row + MANUAL_TRIAGE fallback.
* Severity mapping from :class:`Priority` to :class:`Severity`.
* :class:`DefectAutoFiler.file_for_failed_step` happy path —
  defect row inserted, ``defect.created`` WS broadcast emitted exactly once,
  audit row written, ARQ jobs enqueued.
* Idempotency — second call for same ``(run, case)`` returns ``None``
  (partial unique idx wins).
* No-integration / Slack-only / both-integrations behaviour for ARQ enqueue.
* Auto-filer never raises into the caller (last-resort safety net).

Tests are pure-unit: every collaborator (session, redis, arq pool,
categorizer) is a recorder stub so we don't need a Postgres testcontainer for
this suite. The DB partial unique index is covered indirectly via a fake
:class:`sqlalchemy.exc.IntegrityError`; an integration test exercising the
real index lives alongside the migration tests in ``packages/db``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError
from suitest_api.services.defect_auto_filer import (
    CategorizedDefect,
    DefectAutoFiler,
    DefectCategorizer,
    severity_for_priority,
)
from suitest_db.models.case import TestCase
from suitest_db.models.defect import Defect
from suitest_db.models.integration import Integration
from suitest_db.models.project import Project, Suite
from suitest_db.models.run import Run, RunStep
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

# ---------------------------------------------------------------------------
# DefectCategorizer — one test per _RULES row + fallback
# ---------------------------------------------------------------------------


@pytest.fixture()
def categorizer() -> DefectCategorizer:
    return DefectCategorizer()


def test_categorizer_regression_keyword_status_changed_returns_REGRESSION(
    categorizer: DefectCategorizer,
) -> None:
    assert (
        categorizer.categorize(
            stderr="",
            stdout="",
            assertion_message="Expected 200 OK but got 500 Internal Server Error",
        )
        is DiagnosisKind.REGRESSION
    )


def test_categorizer_status_code_inequality_returns_REGRESSION(
    categorizer: DefectCategorizer,
) -> None:
    assert (
        categorizer.categorize(
            stderr="status 200 != 404",
            stdout="",
            assertion_message=None,
        )
        is DiagnosisKind.REGRESSION
    )


def test_categorizer_flake_keyword_timeout_returns_FLAKE(
    categorizer: DefectCategorizer,
) -> None:
    assert (
        categorizer.categorize(
            stderr="Timeout exceeded while waiting for selector",
            stdout="",
            assertion_message=None,
        )
        is DiagnosisKind.FLAKE
    )


def test_categorizer_intermittent_returns_FLAKE(
    categorizer: DefectCategorizer,
) -> None:
    assert (
        categorizer.categorize(
            stderr="intermittent network error during retry",
            stdout="",
            assertion_message=None,
        )
        is DiagnosisKind.FLAKE
    )


def test_categorizer_infra_keyword_econnrefused_returns_INFRA(
    categorizer: DefectCategorizer,
) -> None:
    assert (
        categorizer.categorize(
            stderr="ECONNREFUSED 127.0.0.1:5432",
            stdout="",
            assertion_message=None,
        )
        is DiagnosisKind.INFRA
    )


def test_categorizer_503_returns_INFRA(
    categorizer: DefectCategorizer,
) -> None:
    assert (
        categorizer.categorize(
            stderr="",
            stdout="HTTP 503 service unavailable",
            assertion_message=None,
        )
        is DiagnosisKind.INFRA
    )


def test_categorizer_spec_drift_jsonpath_no_match_returns_SPEC_DRIFT(
    categorizer: DefectCategorizer,
) -> None:
    assert (
        categorizer.categorize(
            stderr="",
            stdout="",
            assertion_message="jsonpath $.user.email no match",
        )
        is DiagnosisKind.SPEC_DRIFT
    )


def test_categorizer_schema_mismatch_returns_SPEC_DRIFT(
    categorizer: DefectCategorizer,
) -> None:
    assert (
        categorizer.categorize(
            stderr="schema mismatch on response body",
            stdout="",
            assertion_message=None,
        )
        is DiagnosisKind.SPEC_DRIFT
    )


def test_categorizer_unknown_failure_returns_MANUAL_TRIAGE_fallback(
    categorizer: DefectCategorizer,
) -> None:
    assert (
        categorizer.categorize(
            stderr="Unknown error: panic",
            stdout="",
            assertion_message=None,
        )
        is DiagnosisKind.MANUAL_TRIAGE
    )


def test_categorizer_all_empty_inputs_returns_MANUAL_TRIAGE_fallback(
    categorizer: DefectCategorizer,
) -> None:
    assert (
        categorizer.categorize(stderr="", stdout="", assertion_message=None)
        is DiagnosisKind.MANUAL_TRIAGE
    )


def test_categorizer_infra_wins_over_flake_when_both_match(
    categorizer: DefectCategorizer,
) -> None:
    """``_RULES`` order is load-bearing: INFRA precedes FLAKE."""
    assert (
        categorizer.categorize(
            stderr="ECONNREFUSED then timeout",
            stdout="",
            assertion_message=None,
        )
        is DiagnosisKind.INFRA
    )


# ---------------------------------------------------------------------------
# severity_for_priority — full matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("priority", "expected"),
    [
        (Priority.P0, Severity.CRITICAL),
        (Priority.P1, Severity.HIGH),
        (Priority.P2, Severity.MEDIUM),
        (Priority.P3, Severity.LOW),
    ],
)
def test_severity_for_priority_maps_each_priority_to_expected_severity(
    priority: Priority, expected: Severity
) -> None:
    assert severity_for_priority(priority) is expected


def test_severity_for_priority_none_defaults_to_medium() -> None:
    assert severity_for_priority(None) is Severity.MEDIUM


# ---------------------------------------------------------------------------
# DefectAutoFiler — happy path + side effects
# ---------------------------------------------------------------------------


@dataclass
class _RecordingRedis:
    published: dict[str, list[str]] = field(default_factory=dict)

    async def publish(self, channel: str, message: str | bytes) -> int:
        bucket = self.published.setdefault(channel, [])
        bucket.append(message.decode() if isinstance(message, bytes) else message)
        return 1


@dataclass
class _RecordingArqPool:
    enqueued: list[tuple[str, tuple[object, ...], dict[str, object]]] = field(default_factory=list)

    async def enqueue_job(self, name: str, *args: object, **kwargs: object) -> object:
        self.enqueued.append((name, args, kwargs))
        return MagicMock()


@dataclass
class _SessionState:
    """Shared mutable state across the per-call _FakeSession instances."""

    run_step: RunStep | None = None
    run: Run | None = None
    case: TestCase | None = None
    suite: Suite | None = None
    project: Project | None = None
    integrations: list[Integration] = field(default_factory=list)
    inserted_defects: list[Defect] = field(default_factory=list)
    written_audits: list[dict[str, object]] = field(default_factory=list)
    raise_integrity_on_flush: bool = False


class _FakeSession:
    """In-memory ``AsyncSession`` stub satisfying the auto-filer's needs."""

    def __init__(self, state: _SessionState) -> None:
        self._state = state
        self.commit_count = 0
        self.rollback_count = 0

    async def get(self, model: type, id_: str) -> object | None:
        if model is RunStep:
            return self._state.run_step
        if model is Run:
            return self._state.run
        if model is TestCase:
            return self._state.case
        if model is Suite:
            return self._state.suite
        if model is Project:
            return self._state.project
        return None

    def add(self, instance: object) -> None:
        if isinstance(instance, Defect):
            # Mirror the public_id ``before_insert`` listener for the test —
            # the real listener runs at flush time but our session stub
            # short-circuits the dialect, so assign one synthetically.
            if not instance.public_id:
                object.__setattr__(
                    instance, "public_id", f"SUIT-{len(self._state.inserted_defects) + 1}"
                )
            if not instance.id:
                object.__setattr__(instance, "id", f"def_{len(self._state.inserted_defects) + 1}")
            self._state.inserted_defects.append(instance)

    async def flush(self) -> None:
        if self._state.raise_integrity_on_flush:
            raise IntegrityError(
                statement="INSERT INTO defects",
                params={},
                orig=Exception("uq_defects_auto_dedup violation"),
            )

    async def rollback(self) -> None:
        self.rollback_count += 1
        # Reverse the in-memory bookkeeping so dedup tests see no row.
        if self._state.inserted_defects:
            self._state.inserted_defects.pop()

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, _instance: object) -> None:
        return None

    async def scalars(self, _stmt: object) -> _ScalarsResult:
        return _ScalarsResult(self._state.integrations)


@dataclass
class _ScalarsResult:
    rows: list[Integration]

    def all(self) -> list[Integration]:
        return list(self.rows)


def _session_factory(state: _SessionState) -> Callable[[], Any]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[_FakeSession]:
        yield _FakeSession(state)

    return factory


def _make_case(
    *,
    case_id: str = "case_1",
    public_id: str = "TC-42",
    suite_id: str = "suite_1",
    priority: Priority = Priority.P1,
) -> TestCase:
    case = TestCase(
        id=case_id,
        suite_id=suite_id,
        public_id=public_id,
        name="login happy path",
        source=CaseSource.MANUAL,
        status=CaseStatus.ACTIVE,
        priority=priority,
    )
    return case


def _make_run_step(
    *,
    run_step_id: str = "rs_1",
    run_id: str = "run_1",
    case_id: str = "case_1",
    outcome: StepOutcome = StepOutcome.FAIL,
    stderr: str | None = "ECONNREFUSED 127.0.0.1:5432",
    error_message: str | None = "MCP_TOOL_FAILED: connection refused",
    step_order: int = 0,
) -> RunStep:
    rs = RunStep(
        id=run_step_id,
        run_id=run_id,
        case_id=case_id,
        step_order=step_order,
        outcome=outcome,
        stderr=stderr,
        stdout=None,
        error_message=error_message,
    )
    return rs


def _make_run(*, run_id: str = "run_1", project_id: str = "proj_1") -> Run:
    return Run(
        id=run_id,
        public_id="R-1",
        project_id=project_id,
        name="run",
        env="staging",
        trigger=RunTrigger.MANUAL,
        status=RunStatus.RUNNING,
        tier_at_runtime=Tier.ZERO,
    )


def _make_suite(*, suite_id: str = "suite_1", project_id: str = "proj_1") -> Suite:
    return Suite(id=suite_id, project_id=project_id, name="suite-1", order=0)


def _make_project(*, project_id: str = "proj_1", workspace_id: str = "ws_1") -> Project:
    return Project(id=project_id, workspace_id=workspace_id, slug="proj", name="proj")


def _make_slack_integration(*, workspace_id: str = "ws_1") -> Integration:
    return Integration(
        id="int_slack",
        workspace_id=workspace_id,
        kind=IntegrationKind.SLACK,
        name="Slack notifier",
        config={"default_for_notifications": True},
        status="active",
    )


def _make_jira_integration(*, workspace_id: str = "ws_1") -> Integration:
    return Integration(
        id="int_jira",
        workspace_id=workspace_id,
        kind=IntegrationKind.JIRA,
        name="Jira tracker",
        config={"default_for_issues": True},
        status="active",
    )


@pytest.fixture()
def state() -> _SessionState:
    return _SessionState(
        run_step=_make_run_step(),
        run=_make_run(),
        case=_make_case(),
        suite=_make_suite(),
        project=_make_project(),
    )


@pytest.fixture()
def redis() -> _RecordingRedis:
    return _RecordingRedis()


@pytest.fixture()
def arq() -> _RecordingArqPool:
    return _RecordingArqPool()


@pytest.fixture()
def filer(
    state: _SessionState,
    redis: _RecordingRedis,
    arq: _RecordingArqPool,
) -> DefectAutoFiler:
    return DefectAutoFiler(
        session_factory=_session_factory(state),
        publisher=redis,
        arq_pool=arq,
        categorizer=DefectCategorizer(),
    )


# --- happy path ------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_for_failed_step_inserts_defect_with_created_by_system(
    filer: DefectAutoFiler, state: _SessionState
) -> None:
    defect = await filer.file_for_failed_step("rs_1")
    assert defect is not None
    assert defect.created_by == "system"
    assert defect.run_id == "run_1"
    assert defect.test_case_id == "case_1"
    assert defect.agent_diagnosis_kind is DiagnosisKind.INFRA  # ECONNREFUSED → INFRA
    assert defect.severity is Severity.HIGH  # P1 → HIGH
    assert len(state.inserted_defects) == 1


@pytest.mark.asyncio
async def test_file_for_failed_step_emits_defect_created_ws_once(
    filer: DefectAutoFiler, redis: _RecordingRedis
) -> None:
    await filer.file_for_failed_step("rs_1")
    messages = redis.published.get("workspace:ws_1", [])
    assert len(messages) == 1
    payload = json.loads(messages[0])
    assert payload["event"] == "defect.created"
    assert payload["data"]["runId"] == "run_1"
    assert payload["data"]["kind"] == "INFRA"
    assert payload["data"]["severity"] == "HIGH"
    assert payload["data"]["createdBy"] == "system"


# --- dedup -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_for_failed_step_dedup_returns_none_on_integrity_error(
    filer: DefectAutoFiler, state: _SessionState, redis: _RecordingRedis
) -> None:
    """Second call for same (run, case) hits ``uq_defects_auto_dedup`` → None."""
    state.raise_integrity_on_flush = True
    result = await filer.file_for_failed_step("rs_1")
    assert result is None
    # No defect row persisted; no WS broadcast (already broadcast by the
    # original creation).
    assert state.inserted_defects == []
    assert "workspace:ws_1" not in redis.published


@pytest.mark.asyncio
async def test_file_for_failed_step_returns_none_when_run_step_missing(
    filer: DefectAutoFiler, state: _SessionState
) -> None:
    state.run_step = None
    assert await filer.file_for_failed_step("rs_missing") is None
    assert state.inserted_defects == []


@pytest.mark.asyncio
async def test_file_for_failed_step_returns_none_when_case_missing(
    filer: DefectAutoFiler, state: _SessionState
) -> None:
    state.case = None
    assert await filer.file_for_failed_step("rs_1") is None


# --- audit -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_for_failed_step_writes_audit_with_kind_and_severity(
    monkeypatch: pytest.MonkeyPatch, filer: DefectAutoFiler
) -> None:
    """audit row carries (kind, severity, run_id, test_case_id) in metadata."""
    captured: list[dict[str, object]] = []

    async def _capture(
        _session: object,
        *,
        workspace_id: str,
        user_id: str | None,
        action: str,
        resource_type: str,
        resource_id: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        captured.append(
            {
                "workspace_id": workspace_id,
                "user_id": user_id,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "metadata": metadata,
            }
        )

    import suitest_api.services.defect_auto_filer as mod

    monkeypatch.setattr(mod, "write_audit", _capture)
    await filer.file_for_failed_step("rs_1")
    audits = [a for a in captured if a["action"] == "defect.auto_filed"]
    assert len(audits) == 1
    meta = audits[0]["metadata"]
    assert isinstance(meta, dict)
    assert meta["kind"] == "INFRA"
    assert meta["severity"] == "HIGH"
    assert meta["run_id"] == "run_1"
    assert meta["test_case_id"] == "case_1"


# --- integrations / ARQ enqueue --------------------------------------------


@pytest.mark.asyncio
async def test_file_for_failed_step_with_no_integrations_persists_defect_no_enqueue(
    filer: DefectAutoFiler, state: _SessionState, arq: _RecordingArqPool
) -> None:
    """No integrations active → defect persisted, no ARQ jobs."""
    state.integrations = []
    defect = await filer.file_for_failed_step("rs_1")
    assert defect is not None
    assert arq.enqueued == []


@pytest.mark.asyncio
async def test_file_for_failed_step_slack_only_enqueues_send_slack_only(
    filer: DefectAutoFiler, state: _SessionState, arq: _RecordingArqPool
) -> None:
    state.integrations = [_make_slack_integration()]
    await filer.file_for_failed_step("rs_1")
    names = [name for name, _, _ in arq.enqueued]
    assert names == ["send_slack_notification"]
    _, _, kwargs = arq.enqueued[0]
    assert kwargs["integration_id"] == "int_slack"
    assert "defect_id" in kwargs


@pytest.mark.asyncio
async def test_file_for_failed_step_both_integrations_enqueues_both_jobs(
    filer: DefectAutoFiler, state: _SessionState, arq: _RecordingArqPool
) -> None:
    state.integrations = [_make_jira_integration(), _make_slack_integration()]
    await filer.file_for_failed_step("rs_1")
    names = [name for name, _, _ in arq.enqueued]
    assert sorted(names) == sorted(["file_external_issue", "send_slack_notification"])


@pytest.mark.asyncio
async def test_file_for_failed_step_skips_slack_when_default_for_notifications_false(
    filer: DefectAutoFiler, state: _SessionState, arq: _RecordingArqPool
) -> None:
    slack = _make_slack_integration()
    slack.config = {"default_for_notifications": False}
    state.integrations = [slack]
    await filer.file_for_failed_step("rs_1")
    assert arq.enqueued == []


# --- categorizer projection ------------------------------------------------


def test_categorized_defect_namedtuple_shape() -> None:
    cd = CategorizedDefect(
        title="t",
        description="d",
        severity=Severity.LOW,
        diagnosis_kind=DiagnosisKind.FLAKE,
        labels=["l"],
        metadata={"k": "v"},
    )
    assert cd.title == "t"
    assert cd.severity is Severity.LOW
    assert cd.metadata == {"k": "v"}


# --- last-resort safety net ------------------------------------------------


@pytest.mark.asyncio
async def test_file_for_failed_step_swallows_unexpected_exception(
    redis: _RecordingRedis, arq: _RecordingArqPool
) -> None:
    """An exploding session_factory MUST NOT raise into the caller."""

    @asynccontextmanager
    async def boom() -> AsyncIterator[object]:
        raise RuntimeError("synthetic db blackout")
        yield  # pragma: no cover — needed for the generator type

    filer = DefectAutoFiler(
        session_factory=boom,  # type: ignore[arg-type]
        publisher=redis,
        arq_pool=arq,
        categorizer=DefectCategorizer(),
    )
    # The contract: return ``None`` instead of propagating the exception.
    assert await filer.file_for_failed_step("rs_x") is None


# --- target_kind defaulting -------------------------------------------------


def test_run_step_target_kind_helper_smoke() -> None:
    """Confirm the test fixtures construct a RunStep with the right enums.

    Tightly couples the fixture builder to the production enum surface so an
    enum rename surfaces in this suite rather than at runtime.
    """
    rs = _make_run_step()
    assert rs.outcome is StepOutcome.FAIL
    assert _make_case(priority=Priority.P0).priority is Priority.P0
    # TargetKind sanity — verifies the test imports satisfy the type-checker.
    assert TargetKind.FE_WEB.value == "FE_WEB"
