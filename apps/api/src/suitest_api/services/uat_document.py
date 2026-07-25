"""Pure UAT-document assembler — deterministic, ORM-free, ZERO-tier.

Takes already-loaded structural inputs (``CaseInput``) and produces a
``UatDocument`` the renderer turns into a PDF. No DB, no IO — so it unit-tests
with hand-built fixtures exactly like ``junit_report_service.render_junit``.

Status rollup per case: any ERROR/FAIL step -> FAILED; a case with no run step
or only SKIP/PENDING -> NOT RUN; otherwise PASSED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from suitest_shared.domain.enums import StepOutcome

Locale = Literal["id", "en"]
Status = Literal["PASSED", "FAILED", "NOT RUN"]

_SKIP = frozenset({StepOutcome.SKIP, StepOutcome.PENDING})


@dataclass
class StepInput:
    order: int
    action: str
    expected: str


@dataclass
class CaseInput:
    title: str
    suite_name: str
    modul_fitur: str
    steps: list[StepInput]
    run_outcomes: list[StepOutcome]  # the case's latest-run step outcomes ([] = not run)
    evidence: list[str]  # data: URIs (resolved by the loader)


@dataclass
class UatRow:
    no: int
    modul_fitur: str
    test_case: str
    steps: list[str]
    results: list[str]
    status: Status
    evidence: list[str]


@dataclass
class UatSection:
    module_name: str
    rows: list[UatRow] = field(default_factory=list)


@dataclass
class UatDocument:
    title: str
    generated_at: str
    locale: Locale
    pass_pct: int
    sections: list[UatSection] = field(default_factory=list)


def _rollup(outcomes: list[StepOutcome]) -> Status:
    if any(o in (StepOutcome.ERROR, StepOutcome.FAIL) for o in outcomes):
        return "FAILED"
    if not outcomes or all(o in _SKIP for o in outcomes):
        return "NOT RUN"
    return "PASSED"


def assemble_document(
    *, title: str, locale: Locale, generated_at: str, cases: list[CaseInput]
) -> UatDocument:
    """Group cases into per-suite sections and compute statuses + pass %."""
    order: list[str] = []
    sections: dict[str, UatSection] = {}
    passed = 0
    for case in cases:
        if case.suite_name not in sections:
            order.append(case.suite_name)
            sections[case.suite_name] = UatSection(module_name=case.suite_name)
        section = sections[case.suite_name]
        status = _rollup(case.run_outcomes)
        if status == "PASSED":
            passed += 1
        ordered = sorted(case.steps, key=lambda s: s.order)
        section.rows.append(
            UatRow(
                no=len(section.rows) + 1,
                modul_fitur=case.modul_fitur,
                test_case=case.title,
                steps=[s.action for s in ordered],
                results=[s.expected for s in ordered],
                status=status,
                evidence=case.evidence,
            )
        )
    pass_pct = round(passed * 100 / len(cases)) if cases else 0
    return UatDocument(
        title=title,
        generated_at=generated_at,
        locale=locale,
        pass_pct=pass_pct,
        sections=[sections[name] for name in order],
    )
