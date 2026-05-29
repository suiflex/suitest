"""Shared fixtures for the suitest_runner test suite.

Two goals:
* Keep OTel disabled by default so the BatchSpanProcessor doesn't spin up a
  background thread trying to flush to ``localhost:4318`` in CI (same pattern
  as ``apps/api/tests/conftest.py``).
* Provide an in-memory Redis stub via :mod:`fakeredis` so the worker boot /
  enqueue tests run without a live broker.
* Provide ``stub_ctx_with_run`` / ``stub_ctx_all_pass`` / ``stub_ctx_empty``
  fixtures used by the run-orchestrator tests — they inject fake repos /
  invoker / publisher so the orchestrator runs end-to-end without a DB.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fakeredis import aioredis as fake_aioredis
from redis.asyncio import Redis as AsyncRedis
from suitest_mcp.errors import McpToolFailed
from suitest_mcp.models import McpToolResult
from suitest_shared.domain.enums import RunStatus, StepOutcome, TargetKind, Tier

# Disable OpenTelemetry exporter by default in tests — guards against a
# BatchSpanProcessor thread leaking out of import-time setup.
os.environ.setdefault("SUITEST_OTEL_DISABLED", "true")


@pytest.fixture()
def clean_runner_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip ``SUITEST_*`` env so settings tests see defaults.

    Tests that want to assert env-driven values opt in by re-setting the
    relevant variables via :meth:`monkeypatch.setenv` after this fixture runs.
    """
    for key in list(os.environ):
        if key.startswith("SUITEST_"):
            monkeypatch.delenv(key, raising=False)
    yield


@pytest_asyncio.fixture()
async def fake_redis() -> AsyncIterator[AsyncRedis]:
    """In-memory async Redis stub for worker / enqueue tests."""
    client = fake_aioredis.FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Run orchestrator stubs
# ---------------------------------------------------------------------------


@dataclass
class _RecordingRedis:
    """Captures every ``publish`` call to ``published[channel] -> list[message]``."""

    published: dict[str, list[str]] = field(default_factory=dict)

    async def publish(self, channel: str, message: str | bytes) -> int:
        bucket = self.published.setdefault(channel, [])
        bucket.append(message.decode() if isinstance(message, bytes) else message)
        return 1


def _make_step(step_id: str, code: dict[str, Any] | None) -> MagicMock:
    """Build a TestStep stand-in the orchestrator can read attributes off."""
    step = MagicMock()
    step.id = step_id
    step.code = json.dumps(code) if code is not None else None
    step.mcp_provider = "api-http-mcp"
    step.target_kind = TargetKind.BE_REST
    step.action = f"step {step_id}"
    return step


def _make_run(run_id: str = "run-1", project_id: str = "proj-1") -> MagicMock:
    """Build a Run stand-in carrying the columns the orchestrator reads."""
    run = MagicMock()
    run.id = run_id
    run.project_id = project_id
    run.triggered_by = "user-1"
    run.status = RunStatus.QUEUED
    return run


def _make_capability(workspace_id: str = "ws-1") -> MagicMock:
    """Build a WorkspaceCapability stand-in pinned to ZERO tier."""
    cap = MagicMock()
    cap.workspace_id = workspace_id
    cap.tier = Tier.ZERO
    cap.features_json = {}
    return cap


def _make_project(project_id: str = "proj-1", workspace_id: str = "ws-1") -> MagicMock:
    """Build a Project stand-in the orchestrator looks up via ``session.get``."""
    proj = MagicMock()
    proj.id = project_id
    proj.workspace_id = workspace_id
    return proj


class _FakeSession:
    """Bare-minimum SQLAlchemy AsyncSession stand-in for the orchestrator.

    The orchestrator only calls ``session.get(Project, project_id)`` directly
    and threads the session into the repo classes (which we monkeypatch).
    Everything else (``commit`` / ``flush``) is a no-op recorder.
    """

    def __init__(self, project: MagicMock) -> None:
        self._project = project
        self.commits = 0

    async def get(self, _model: object, _id: object) -> MagicMock:
        return self._project

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        return None

    def add(self, _instance: object) -> None:
        return None


def _session_factory(project: MagicMock) -> Any:
    """Return a callable that yields a fresh session-context per call."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[_FakeSession]:
        yield _FakeSession(project)

    return factory


def _install_repo_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    run: MagicMock | None,
    selection: list[tuple[str, int, MagicMock]],
    capability: MagicMock | None,
    inserted_steps: list[dict[str, object]],
) -> None:
    """Monkeypatch the three repo classes the orchestrator instantiates.

    The fakes ignore the ``session`` they're constructed with — they return
    pre-baked data from the closures above. ``inserted_steps`` is a list the
    test asserts against (one entry per ``RunStepRepo.create_step`` call).
    """

    class _FakeRunRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def get_with_selection(
            self, _run_id: str
        ) -> tuple[MagicMock | None, list[tuple[str, int, MagicMock]]]:
            return run, selection if run is not None else []

        async def get_by_id(self, _run_id: str) -> MagicMock | None:
            return run

        async def update_status(self, _run_id: str, status: RunStatus, **kwargs: object) -> None:
            return None

    class _FakeWorkspaceCapRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def get(self, _workspace_id: str) -> MagicMock | None:
            return capability

    class _FakeRunStepRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def create_step(self, **kwargs: object) -> MagicMock:
            row = MagicMock()
            row.id = f"rs-{len(inserted_steps)}"
            inserted_steps.append(kwargs)
            return row

    import suitest_runner.jobs.run_test_case as job_mod

    monkeypatch.setattr(job_mod, "RunRepo", _FakeRunRepo)
    monkeypatch.setattr(job_mod, "WorkspaceCapabilityRepo", _FakeWorkspaceCapRepo)
    monkeypatch.setattr(job_mod, "RunStepRepo", _FakeRunStepRepo)


class _FakeRegistry:
    """Minimal :class:`McpRegistry` stand-in.

    The orchestrator checks ``workspace_id in registry._by_workspace`` to
    decide whether to lazy-load — pre-seeding that dict is enough to skip
    the load path.
    """

    def __init__(self, workspace_id: str = "ws-1") -> None:
        self._by_workspace: dict[str, dict[str, object]] = {workspace_id: {}}

    async def load_for_workspace(self, _session: object, _workspace_id: str) -> None:
        return None


def _make_invoker(outcomes: list[str]) -> MagicMock:
    """Build an invoker that returns ok / raises FAIL by step order.

    ``outcomes`` is a list aligned with the selection order: ``"PASS"`` /
    ``"FAIL"`` / ``"ERROR"`` decide what the n-th invocation does. We use
    ``MagicMock(spec=McpInvoker)`` so the orchestrator's ``isinstance`` guard
    accepts the stub without us hand-rolling all the invoker's wiring.
    """
    from suitest_mcp.invoker import McpInvoker

    inv = MagicMock(spec=McpInvoker)
    state = {"i": 0}

    async def _invoke(
        *,
        explicit_provider: str,
        tool: str,
        arguments: dict[str, object],
        ctx: object,
    ) -> McpToolResult:
        idx = state["i"]
        state["i"] += 1
        outcome = outcomes[idx] if idx < len(outcomes) else "PASS"
        if outcome == "FAIL":
            raise McpToolFailed("simulated assertion failed")
        return McpToolResult(ok=True, output={}, stdout="{}", duration_ms=10)

    inv.invoke = _invoke
    return inv


def _make_registry_instance() -> MagicMock:
    """Build a registry pre-seeded with the fixture workspace.

    ``MagicMock(spec=McpRegistry)`` satisfies the orchestrator's ``isinstance``
    guard; we then override ``_by_workspace`` so the lazy-load branch is
    short-circuited.
    """
    from suitest_mcp.registry import McpRegistry

    reg = MagicMock(spec=McpRegistry)
    reg._by_workspace = {"ws-1": {}}
    return reg


def _build_ctx(
    monkeypatch: pytest.MonkeyPatch,
    *,
    outcomes: list[str],
    steps: list[MagicMock] | None = None,
    run: MagicMock | None = None,
    capability: MagicMock | None = None,
    use_default_run: bool = True,
) -> tuple[dict[str, object], _RecordingRedis, list[dict[str, object]]]:
    """Assemble a full ctx + a recorder + a steps-insert list for one orchestrator run.

    ``use_default_run=False`` opts out of the default ``_make_run()`` fallback
    so callers can express the "missing run" scenario by passing ``run=None``.
    """
    if run is None and use_default_run:
        run = _make_run()
    capability = capability if capability is not None else _make_capability()
    if steps is None:
        steps = [_make_step(f"s{i}", {"tool": "t", "arguments": {}}) for i in range(len(outcomes))]
    selection: list[tuple[str, int, MagicMock]] = [
        ("case-1", idx, step) for idx, step in enumerate(steps)
    ]
    inserted_steps: list[dict[str, object]] = []
    project = _make_project()
    _install_repo_stubs(
        monkeypatch,
        run=run,
        selection=selection,
        capability=capability,
        inserted_steps=inserted_steps,
    )
    redis_stub = _RecordingRedis()
    ctx: dict[str, object] = {
        "session_factory": _session_factory(project),
        "redis": redis_stub,
        "invoker": _make_invoker(outcomes),
        "registry": _make_registry_instance(),
        "_inserted_steps": inserted_steps,
    }
    return ctx, redis_stub, inserted_steps


@pytest.fixture()
def stub_ctx_with_run(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, object], _RecordingRedis]:
    """3 steps: 2 PASS + 1 FAIL — the headline orchestrator fixture."""
    ctx, redis_stub, _ = _build_ctx(monkeypatch, outcomes=["PASS", "FAIL", "PASS"])
    return ctx, redis_stub


@pytest.fixture()
def stub_ctx_all_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, object], _RecordingRedis]:
    """3 steps, all PASS — exercises the happy ``RunStatus.PASS`` path."""
    ctx, redis_stub, _ = _build_ctx(monkeypatch, outcomes=["PASS", "PASS", "PASS"])
    return ctx, redis_stub


@pytest.fixture()
def stub_ctx_empty(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """``RunRepo.get_with_selection`` returns ``(None, [])`` — missing-run path."""
    ctx, _, _ = _build_ctx(
        monkeypatch,
        outcomes=[],
        steps=[],
        run=None,
        use_default_run=False,
    )
    return ctx


# Re-exports used by tests
__all__ = [
    "StepOutcome",
    "clean_runner_env",
    "fake_redis",
    "stub_ctx_all_pass",
    "stub_ctx_empty",
    "stub_ctx_with_run",
]
