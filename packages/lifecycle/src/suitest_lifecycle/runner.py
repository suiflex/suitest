"""Execute exported test files and collect structured results.

Each ``TCxxx.py`` is runnable standalone (its ``__main__`` calls the test fn), so
we execute it with the current interpreter, capture stdout/stderr, and map the
exit code to a :class:`TestResult`. A non-zero exit (e.g. ``AssertionError``)
becomes ``FAILED`` with the captured traceback as the error message.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

from suitest_lifecycle.models import PlanCase, StepResult, TestOutcome, TestResult

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _collect_steps(
    case: PlanCase, test_dir: Path, outcome: TestOutcome
) -> tuple[list[StepResult], str, str]:
    """Read the test's ``<TC>.result.json`` sidecar (frontend) or derive steps
    from the plan (backend). Returns (steps, video_path, screenshot_path)."""
    sidecar = test_dir / f"{case.id}.result.json"
    if sidecar.is_file():
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        steps = [
            StepResult(
                index=int(s.get("index", i + 1)),
                type=str(s.get("type", "action")),
                description=str(s.get("description", "")),
                status=_as_outcome(str(s.get("status", "PASSED"))),
                screenshot_path=str(s.get("screenshot") or ""),
            )
            for i, s in enumerate(data.get("steps", []) or [])
            if isinstance(s, dict)
        ]
        return steps, str(data.get("video") or ""), str(data.get("screenshot") or "")
    # Backend (no sidecar): derive from the plan steps, marking the last failed
    # when the test failed so the Steps panel still shows where it broke.
    steps = []
    n = len(case.steps)
    for i, ps in enumerate(case.steps):
        st = TestOutcome.PASSED
        if outcome in (TestOutcome.FAILED, TestOutcome.ERROR) and i == n - 1:
            st = outcome
        steps.append(StepResult(index=i + 1, type=ps.type, description=ps.description, status=st))
    return steps, "", ""


def _as_outcome(value: str) -> TestOutcome:
    try:
        return TestOutcome(value.upper())
    except ValueError:
        return TestOutcome.PASSED


def _tail(text: str | None, lines: int = 500) -> str:
    # ponytail: 500-line tail bound keeps the ingest payload sane for chatty tests.
    return "\n".join((text or "").strip().splitlines()[-lines:])


def _run_one(
    file_path: Path, python: str, timeout_sec: int, env: dict[str, str] | None = None
) -> tuple[TestOutcome, int, str, str, str]:
    """Returns (outcome, duration_ms, error, stdout_tail, stderr_tail)."""
    start = time.monotonic()
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    try:
        proc = subprocess.run(
            [python, str(file_path)],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(file_path.parent),
            env=process_env,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return (
            TestOutcome.ERROR,
            int((time.monotonic() - start) * 1000),
            f"timeout after {timeout_sec}s",
            _tail(out),
            _tail(err),
        )
    duration_ms = int((time.monotonic() - start) * 1000)
    out_tail = _tail(proc.stdout)
    err_tail_full = _tail(proc.stderr)
    if proc.returncode == 0:
        return TestOutcome.PASSED, duration_ms, "", out_tail, err_tail_full
    err = (proc.stderr or "").strip() or (proc.stdout or "").strip() or f"exit {proc.returncode}"
    # Keep the last ~30 lines — enough to see the assertion without flooding the report.
    err_tail = "\n".join(err.splitlines()[-30:])
    return TestOutcome.FAILED, duration_ms, err_tail, out_tail, err_tail_full


def run_tests(
    cases: list[PlanCase],
    test_dir: Path,
    *,
    selected_ids: list[str] | None = None,
    python: str | None = None,
    timeout_sec: int = 120,
    on_result: Callable[[TestResult], None] | None = None,
    env: dict[str, str] | None = None,
) -> list[TestResult]:
    interpreter = python or sys.executable
    wanted = set(selected_ids) if selected_ids else None
    results: list[TestResult] = []
    for case in cases:
        if wanted is not None and case.id not in wanted:
            continue
        if not case.automation_file:
            result = TestResult(
                test_id=case.id,
                title=case.title,
                description=case.description,
                status=TestOutcome.SKIPPED,
                duration_ms=0,
                error="no automation file exported",
            )
            results.append(result)
            if on_result is not None:
                on_result(result)
            continue
        file_path = test_dir / case.automation_file
        outcome, duration_ms, error, out_tail, err_tail = _run_one(
            file_path, interpreter, timeout_sec, env
        )
        steps, video, screenshot = _collect_steps(case, test_dir, outcome)
        artifacts = [p for p in (video, screenshot) if p]
        result = TestResult(
            test_id=case.id,
            title=case.title,
            description=case.description,
            status=outcome,
            duration_ms=duration_ms,
            error=error,
            automation_file=case.automation_file,
            stdout=out_tail,
            stderr=err_tail,
            steps=steps,
            video_path=video,
            screenshot_path=screenshot,
            artifacts=artifacts,
        )
        results.append(result)
        if on_result is not None:
            on_result(result)
    return results


__all__ = ["run_tests"]
