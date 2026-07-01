"""Execute exported test files and collect structured results.

Each ``TCxxx.py`` is runnable standalone (its ``__main__`` calls the test fn), so
we execute it with the current interpreter, capture stdout/stderr, and map the
exit code to a :class:`TestResult`. A non-zero exit (e.g. ``AssertionError``)
becomes ``FAILED`` with the captured traceback as the error message.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from suitest_lifecycle.models import PlanCase, StepResult, TestOutcome, TestResult


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


def _run_one(file_path: Path, python: str, timeout_sec: int) -> tuple[TestOutcome, int, str]:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            [python, str(file_path)],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(file_path.parent),
        )
    except subprocess.TimeoutExpired:
        return TestOutcome.ERROR, int((time.monotonic() - start) * 1000), f"timeout after {timeout_sec}s"
    duration_ms = int((time.monotonic() - start) * 1000)
    if proc.returncode == 0:
        return TestOutcome.PASSED, duration_ms, ""
    err = (proc.stderr or "").strip() or (proc.stdout or "").strip() or f"exit {proc.returncode}"
    # Keep the last ~30 lines — enough to see the assertion without flooding the report.
    err_tail = "\n".join(err.splitlines()[-30:])
    return TestOutcome.FAILED, duration_ms, err_tail


def run_tests(
    cases: list[PlanCase],
    test_dir: Path,
    *,
    selected_ids: list[str] | None = None,
    python: str | None = None,
    timeout_sec: int = 120,
) -> list[TestResult]:
    interpreter = python or sys.executable
    wanted = set(selected_ids) if selected_ids else None
    results: list[TestResult] = []
    for case in cases:
        if wanted is not None and case.id not in wanted:
            continue
        if not case.automation_file:
            results.append(
                TestResult(
                    test_id=case.id,
                    title=case.title,
                    description=case.description,
                    status=TestOutcome.SKIPPED,
                    duration_ms=0,
                    error="no automation file exported",
                )
            )
            continue
        file_path = test_dir / case.automation_file
        outcome, duration_ms, error = _run_one(file_path, interpreter, timeout_sec)
        steps, video, screenshot = _collect_steps(case, test_dir, outcome)
        artifacts = [p for p in (video, screenshot) if p]
        results.append(
            TestResult(
                test_id=case.id,
                title=case.title,
                description=case.description,
                status=outcome,
                duration_ms=duration_ms,
                error=error,
                automation_file=case.automation_file,
                steps=steps,
                video_path=video,
                screenshot_path=screenshot,
                artifacts=artifacts,
            )
        )
    return results


__all__ = ["run_tests"]
