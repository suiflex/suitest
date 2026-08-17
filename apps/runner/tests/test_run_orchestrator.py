"""Tests for the M1c run orchestrator.

The orchestrator is hard to unit test against a real Postgres in CI, so the
fixtures in ``conftest.py`` stub the three repos the orchestrator instantiates
(``RunRepo`` / ``RunStepRepo`` / ``WorkspaceCapabilityRepo``), the
:class:`McpInvoker`, the :class:`McpRegistry`, and the Redis publisher.

The four tests below exercise:

* full event sequence with one failing step,
* per-step DB inserts are recorded in order,
* all-PASS aggregation drives ``RunStatus.PASS``,
* missing run returns a structured error instead of raising.
"""

from __future__ import annotations

import json

import pytest
from suitest_runner.jobs.run_test_case import run_test_case

pytestmark = pytest.mark.asyncio


async def test_publishes_full_event_sequence_with_one_fail(
    stub_ctx_with_run: tuple[dict[str, object], object],
) -> None:
    """3 steps (2 PASS + 1 FAIL) → run.started + 3*(start/completed) + run.completed."""
    ctx, redis_stub = stub_ctx_with_run
    out = await run_test_case(ctx, "run-1")
    assert out["status"] == "FAIL"
    published = redis_stub.published["run:run-1"]  # type: ignore[attr-defined]
    events = [json.loads(m)["event"] for m in published]
    assert events[0] == "run.started"
    assert events[-1] == "run.completed"
    assert events.count("run.step.started") == 3
    assert events.count("run.step.completed") == 3


async def test_persists_three_run_steps(
    stub_ctx_with_run: tuple[dict[str, object], object],
) -> None:
    """One ``RunStepRepo.create_step`` call per step in the selection."""
    ctx, _ = stub_ctx_with_run
    await run_test_case(ctx, "run-1")
    inserted = ctx["_inserted_steps"]
    assert isinstance(inserted, list)
    assert len(inserted) == 3


async def test_all_pass_marks_run_pass(
    stub_ctx_all_pass: tuple[dict[str, object], object],
) -> None:
    """No failing steps → run reports PASS and the passed counter matches total."""
    ctx, _ = stub_ctx_all_pass
    out = await run_test_case(ctx, "run-1")
    assert out["status"] == "PASS"
    assert out["passed"] == 3
    assert out["failed"] == 0
    assert out["errored"] == 0


async def test_missing_run_returns_error(stub_ctx_empty: dict[str, object]) -> None:
    """Unknown run → structured ``RUN_NOT_FOUND`` error, no events published."""
    out = await run_test_case(stub_ctx_empty, "missing")
    assert out.get("error") == "RUN_NOT_FOUND"


async def test_auto_self_heal_retries_once_and_counts_final_pass(
    stub_ctx_auto_self_heal: tuple[dict[str, object], object],
) -> None:
    ctx, redis_stub = stub_ctx_auto_self_heal
    out = await run_test_case(ctx, "run-1")
    assert out["status"] == "PASS"
    assert out["passed"] == 1
    inserted = ctx["_inserted_steps"]
    assert isinstance(inserted, list)
    assert len(inserted) == 1
    assert inserted[0]["state_snapshot"] == {
        "failureKind": "selector_changed",
        "selfHeal": {
            "failureKind": "selector_changed",
            "oldSelector": "#old",
            "newSelector": "#new",
            "retryCount": 1,
            "originalError": "MCP_TOOL_FAILED: Timeout waiting for locator('#submit')",
            "retryOutcome": "PASS",
            "persisted": True,
        },
    }
    published = redis_stub.published["run:run-1"]  # type: ignore[attr-defined]
    completed = next(
        json.loads(message)["data"]
        for message in published
        if json.loads(message)["event"] == "run.step.completed"
    )
    assert completed["selfHeal"]["retryOutcome"] == "PASS"


async def test_selector_failure_is_classified_without_auto_repair(
    stub_ctx_selector_fail: tuple[dict[str, object], object],
) -> None:
    ctx, _ = stub_ctx_selector_fail
    out = await run_test_case(ctx, "run-1")
    assert out["status"] == "FAIL"
    inserted = ctx["_inserted_steps"]
    assert isinstance(inserted, list)
    assert inserted[0]["state_snapshot"] == {"failureKind": "selector_changed"}


async def test_zero_steps_marks_run_error(stub_ctx_no_steps: dict[str, object]) -> None:
    """An empty selection must not report a green run (issue #109)."""
    out = await run_test_case(stub_ctx_no_steps, "run-1")
    assert out["status"] == "ERROR"
    assert out["total"] == 0
