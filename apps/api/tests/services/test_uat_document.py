"""Pure assembler tests — grouping, per-section numbering, status rollup, pass %.

ORM-free: hand-built CaseInput fixtures, no DB/session (mirrors junit tests)."""

from __future__ import annotations

from suitest_api.services.uat_document import (
    CaseInput,
    StepInput,
    assemble_document,
)
from suitest_shared.domain.enums import StepOutcome as SO


def _case(
    title: str,
    suite: str,
    modul: str,
    outcomes: list[SO],
    *,
    evidence: list[str] | None = None,
) -> CaseInput:
    return CaseInput(
        title=title,
        suite_name=suite,
        modul_fitur=modul,
        steps=[StepInput(order=1, action="do a thing", expected="it works")],
        run_outcomes=outcomes,
        evidence=evidence or [],
    )


def test_groups_by_suite_and_numbers_per_section() -> None:
    doc = assemble_document(
        title="UAT Portal",
        locale="id",
        generated_at="29 Juni 2026",
        cases=[
            _case("Logo", "Login", "Header", [SO.PASS]),
            _case("Form", "Login", "Form", [SO.PASS]),
            _case("Chart", "Dashboard", "Overview", [SO.PASS]),
        ],
    )
    assert [s.module_name for s in doc.sections] == ["Login", "Dashboard"]
    assert [r.no for r in doc.sections[0].rows] == [1, 2]
    assert doc.sections[1].rows[0].no == 1
    assert doc.sections[0].rows[0].modul_fitur == "Header"


def test_status_rollup() -> None:
    doc = assemble_document(
        title="t",
        locale="id",
        generated_at="x",
        cases=[
            _case("ok", "S", "m", [SO.PASS, SO.PASS]),
            _case("fail", "S", "m", [SO.PASS, SO.FAIL]),
            _case("err", "S", "m", [SO.ERROR]),
            _case("none", "S", "m", []),
            _case("skip", "S", "m", [SO.SKIP, SO.PENDING]),
        ],
    )
    statuses = [r.status for r in doc.sections[0].rows]
    assert statuses == ["PASSED", "FAILED", "FAILED", "NOT RUN", "NOT RUN"]


def test_pass_pct_counts_only_passed_over_total() -> None:
    doc = assemble_document(
        title="t",
        locale="id",
        generated_at="x",
        cases=[
            _case("a", "S", "m", [SO.PASS]),
            _case("b", "S", "m", [SO.PASS]),
            _case("c", "S", "m", [SO.FAIL]),
            _case("d", "S", "m", []),
        ],
    )
    assert doc.pass_pct == 50  # 2 passed / 4 total


def test_steps_and_results_preserved_in_order() -> None:
    c = CaseInput(
        title="multi",
        suite_name="S",
        modul_fitur="m",
        steps=[
            StepInput(order=2, action="second", expected="r2"),
            StepInput(order=1, action="first", expected="r1"),
        ],
        run_outcomes=[SO.PASS],
        evidence=[],
    )
    doc = assemble_document(title="t", locale="id", generated_at="x", cases=[c])
    row = doc.sections[0].rows[0]
    assert row.steps == ["first", "second"]  # sorted by order
    assert row.results == ["r1", "r2"]


def test_empty_selection_is_empty_doc_100_guard() -> None:
    doc = assemble_document(title="t", locale="id", generated_at="x", cases=[])
    assert doc.sections == []
    assert doc.pass_pct == 0
