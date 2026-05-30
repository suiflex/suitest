"""Tests for the M1d-10 runner step-failed hook.

Covers two surfaces:

* :func:`suitest_runner.handlers.step_handler.on_run_step_failed` — direct
  unit tests asserting the hook's no-throw contract and that it forwards the
  ``run_step.id`` to the injected auto-filer.

* :func:`suitest_runner.jobs.run_test_case.run_test_case` orchestrator —
  end-to-end fixture-driven test asserting that on ``StepOutcome.FAIL`` the
  orchestrator looks up ``ctx['defect_auto_filer']`` and calls
  :meth:`file_for_failed_step` with the inserted ``RunStep.id``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from suitest_runner.handlers.step_handler import on_run_step_failed
from suitest_runner.jobs.run_test_case import run_test_case
from suitest_shared.domain.enums import DiagnosisKind, Severity

pytestmark = pytest.mark.asyncio


class _RecordingAutoFiler:
    """Stand-in for ``DefectAutoFiler`` that records every invocation."""

    def __init__(
        self,
        *,
        returns: Any = None,
        raises: type[Exception] | None = None,
    ) -> None:
        self.calls: list[str] = []
        self._returns = returns
        self._raises = raises

    async def file_for_failed_step(self, run_step_id: str) -> Any:
        self.calls.append(run_step_id)
        if self._raises is not None:
            raise self._raises("synthetic")
        return self._returns


def _fake_run_step(run_step_id: str = "rs_1") -> MagicMock:
    rs = MagicMock()
    rs.id = run_step_id
    return rs


# ---------------------------------------------------------------------------
# Direct hook unit tests
# ---------------------------------------------------------------------------


async def test_on_run_step_failed_calls_auto_filer_with_step_id() -> None:
    rs = _fake_run_step("rs_42")
    filer = _RecordingAutoFiler()
    await on_run_step_failed(auto_filer=filer, run_step=rs)  # type: ignore[arg-type]
    assert filer.calls == ["rs_42"]


async def test_on_run_step_failed_no_auto_filer_is_noop() -> None:
    """``auto_filer=None`` must not raise — runner deployed standalone."""
    await on_run_step_failed(auto_filer=None, run_step=_fake_run_step())


async def test_on_run_step_failed_swallows_auto_filer_exception() -> None:
    """Auto-filer exceptions must NOT bubble into the runner orchestrator."""
    filer = _RecordingAutoFiler(raises=RuntimeError)
    # Must not raise.
    await on_run_step_failed(auto_filer=filer, run_step=_fake_run_step())  # type: ignore[arg-type]
    assert filer.calls == ["rs_1"]


async def test_on_run_step_failed_logs_when_defect_inserted() -> None:
    """Successful insert path returns a Defect — hook logs but doesn't raise."""
    defect = MagicMock()
    defect.id = "def_1"
    defect.severity = Severity.HIGH
    defect.agent_diagnosis_kind = DiagnosisKind.INFRA
    filer = _RecordingAutoFiler(returns=defect)
    await on_run_step_failed(auto_filer=filer, run_step=_fake_run_step())  # type: ignore[arg-type]


async def test_on_run_step_failed_handles_none_return_from_filer() -> None:
    """Dedup path returns None — hook must not crash."""
    filer = _RecordingAutoFiler(returns=None)
    await on_run_step_failed(auto_filer=filer, run_step=_fake_run_step("rs_dup"))  # type: ignore[arg-type]
    assert filer.calls == ["rs_dup"]


# ---------------------------------------------------------------------------
# Orchestrator integration: ctx['defect_auto_filer'] is invoked on FAIL
# ---------------------------------------------------------------------------


async def test_run_test_case_invokes_auto_filer_on_failed_step(
    stub_ctx_with_run: tuple[dict[str, object], object],
) -> None:
    """3 steps (PASS, FAIL, PASS) → auto-filer called exactly once on the FAIL."""
    ctx, _ = stub_ctx_with_run
    filer = _RecordingAutoFiler()
    ctx["defect_auto_filer"] = filer
    await run_test_case(ctx, "run-1")
    # One FAIL → one auto-filer call. The RunStep.id comes from the stub
    # repo's monotonic counter ("rs-0", "rs-1", "rs-2"); the second step
    # (index 1) failed.
    assert filer.calls == ["rs-1"]


async def test_run_test_case_no_filer_in_ctx_runs_to_completion(
    stub_ctx_with_run: tuple[dict[str, object], object],
) -> None:
    """Missing ``defect_auto_filer`` in ctx → orchestrator still completes."""
    ctx, _ = stub_ctx_with_run
    # No defect_auto_filer key set.
    out = await run_test_case(ctx, "run-1")
    assert out["status"] == "FAIL"
    assert out["failed"] == 1


async def test_run_test_case_auto_filer_raises_does_not_break_run(
    stub_ctx_with_run: tuple[dict[str, object], object],
) -> None:
    """Exploding auto-filer must NOT corrupt the run's terminal status."""
    ctx, _ = stub_ctx_with_run
    filer = _RecordingAutoFiler(raises=RuntimeError)
    ctx["defect_auto_filer"] = filer
    out = await run_test_case(ctx, "run-1")
    assert out["status"] == "FAIL"
    assert out["failed"] == 1


async def test_run_test_case_non_filer_object_in_ctx_is_skipped(
    stub_ctx_with_run: tuple[dict[str, object], object],
) -> None:
    """Some random object in ctx (no ``file_for_failed_step``) → skipped silently."""
    ctx, _ = stub_ctx_with_run
    ctx["defect_auto_filer"] = object()  # ← lacks file_for_failed_step
    out = await run_test_case(ctx, "run-1")
    assert out["status"] == "FAIL"
