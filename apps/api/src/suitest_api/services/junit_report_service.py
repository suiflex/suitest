"""JUnit XML report for a run — CI-consumable bundle result (#2, QA-automation lens).

Maps each Suitest test CASE in a run to one JUnit ``<testcase>``, rolling up its
``RunStep`` outcomes: ERROR if any step errored, FAILURE if any step failed,
SKIPPED if every step skipped/pending, else PASS. ``time`` is the summed step
duration. Pure + deterministic + ZERO-tier — a function of the persisted run
steps, no LLM. Output is Jenkins / GitHub-Actions consumable so a Suitest run can
gate a CI pipeline (``<testsuites><testsuite><testcase>``).

The renderer takes a structural ``_StepLike`` protocol (not the ORM row) so it
unit-tests without a database; the ``RunStep`` model satisfies it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from xml.etree.ElementTree import Element, SubElement, tostring

from suitest_shared.domain.enums import StepOutcome

# Outcomes that count a case as "skipped" when ALL its steps are in this set.
_SKIP_OUTCOMES: frozenset[StepOutcome] = frozenset({StepOutcome.SKIP, StepOutcome.PENDING})


class _StepLike(Protocol):
    """Structural view of a ``RunStep`` the renderer needs (keeps it ORM-free)."""

    case_id: str
    step_order: int
    outcome: StepOutcome
    duration_ms: int | None
    error_message: str | None


def _fmt_time(ms_total: int) -> str:
    """Milliseconds → JUnit seconds string (3 dp), e.g. ``1500`` → ``"1.500"``."""
    return f"{ms_total / 1000.0:.3f}"


class _CaseRollup:
    """Accumulates one Suitest case's steps into a single JUnit testcase verdict."""

    __slots__ = ("_errored", "_failed", "_message", "_non_skip", "duration_ms", "public_id")

    def __init__(self, public_id: str) -> None:
        self.public_id = public_id
        self.duration_ms = 0
        self._errored = False
        self._failed = False
        self._non_skip = False  # any step that ran to a non-skip/pending outcome
        self._message: str | None = None

    def add(self, step: _StepLike) -> None:
        self.duration_ms += step.duration_ms or 0
        if step.outcome is StepOutcome.ERROR:
            self._errored = True
            self._non_skip = True
            self._remember(step.error_message)
        elif step.outcome is StepOutcome.FAIL:
            self._failed = True
            self._non_skip = True
            self._remember(step.error_message)
        elif step.outcome not in _SKIP_OUTCOMES:
            self._non_skip = True

    def _remember(self, message: str | None) -> None:
        # Keep the FIRST failing/erroring step's message — that's the root signal.
        if self._message is None:
            self._message = message or ""

    @property
    def verdict(self) -> str:
        """One of ``error`` / ``failure`` / ``skipped`` / ``passed``.

        ERROR wins over FAIL (an erroring step is a harder fault than an assertion
        failure). A case is ``skipped`` only when NO step produced a real outcome
        (every step skipped/pending) — e.g. a ZERO-tier run of a prose-only case.
        """
        if self._errored:
            return "error"
        if self._failed:
            return "failure"
        if not self._non_skip:
            return "skipped"
        return "passed"

    @property
    def message(self) -> str:
        return self._message or ""


def render_junit(run_name: str, steps: Sequence[tuple[_StepLike, str]]) -> str:
    """Render a run's steps as a JUnit XML document.

    ``steps`` is a sequence of ``(run_step, case_public_id)`` pairs (as returned by
    ``RunRepo.get_steps_with_case_public_id``). Steps are grouped into testcases by
    case, preserving first-seen case order and sorting each case's steps by
    ``step_order``. A run with zero steps renders an empty (but valid) suite.
    """
    # Group preserving first-seen case order; sort steps within a case by order.
    order: list[str] = []
    grouped: dict[str, _CaseRollup] = {}
    by_case: dict[str, list[_StepLike]] = {}
    for step, public_id in steps:
        if step.case_id not in grouped:
            order.append(step.case_id)
            grouped[step.case_id] = _CaseRollup(public_id)
            by_case[step.case_id] = []
        by_case[step.case_id].append(step)
    for case_id in order:
        for step in sorted(by_case[case_id], key=lambda s: s.step_order):
            grouped[case_id].add(step)

    rollups = [grouped[cid] for cid in order]
    tests = len(rollups)
    failures = sum(1 for r in rollups if r.verdict == "failure")
    errors = sum(1 for r in rollups if r.verdict == "error")
    skipped = sum(1 for r in rollups if r.verdict == "skipped")
    total_ms = sum(r.duration_ms for r in rollups)

    suites_attrs = {
        "name": run_name,
        "tests": str(tests),
        "failures": str(failures),
        "errors": str(errors),
        "skipped": str(skipped),
        "time": _fmt_time(total_ms),
    }
    root = Element("testsuites", suites_attrs)
    suite = SubElement(root, "testsuite", suites_attrs)
    for r in rollups:
        tc = SubElement(
            suite,
            "testcase",
            {"name": r.public_id, "classname": run_name, "time": _fmt_time(r.duration_ms)},
        )
        verdict = r.verdict
        if verdict == "error":
            SubElement(tc, "error", {"message": r.message}).text = r.message or None
        elif verdict == "failure":
            SubElement(tc, "failure", {"message": r.message}).text = r.message or None
        elif verdict == "skipped":
            SubElement(tc, "skipped")
    body = tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body
