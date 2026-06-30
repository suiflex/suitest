"""Unit tests for render_junit — pure, no DB, deterministic (ZERO-tier).

Exercises the per-case rollup (error > failure > skipped > passed), the suite-level
tally attributes, time summing, message capture, and XML escaping. Uses a tiny
dataclass that satisfies the ``_StepLike`` protocol so no ORM/session is needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree.ElementTree import fromstring

from suitest_api.services.junit_report_service import render_junit
from suitest_shared.domain.enums import StepOutcome


@dataclass
class _Step:
    case_id: str
    step_order: int
    outcome: StepOutcome
    duration_ms: int | None
    error_message: str | None = None


def _steps(*rows: _Step) -> list[tuple[_Step, str]]:
    """Pair each step with a case public id (TC-<case_id-suffix>)."""
    return [(s, f"TC-{s.case_id}") for s in rows]


def test_passed_case_has_no_child_nodes() -> None:
    xml = render_junit(
        "smoke",
        _steps(
            _Step("a", 1, StepOutcome.PASS, 100),
            _Step("a", 2, StepOutcome.PASS, 150),
        ),
    )
    root = fromstring(xml)
    assert root.tag == "testsuites"
    assert root.attrib["tests"] == "1"
    assert root.attrib["failures"] == "0"
    assert root.attrib["errors"] == "0"
    assert root.attrib["skipped"] == "0"
    assert root.attrib["time"] == "0.250"
    case = root.find("./testsuite/testcase")
    assert case is not None
    assert case.attrib["name"] == "TC-a"
    assert case.attrib["classname"] == "smoke"
    assert case.attrib["time"] == "0.250"
    assert list(case) == []  # no failure/error/skipped child


def test_failure_when_any_step_fails() -> None:
    xml = render_junit(
        "smoke",
        _steps(
            _Step("a", 1, StepOutcome.PASS, 100),
            _Step("a", 2, StepOutcome.FAIL, 50, error_message="expected 200 got 500"),
        ),
    )
    root = fromstring(xml)
    assert root.attrib["tests"] == "1"
    assert root.attrib["failures"] == "1"
    assert root.attrib["errors"] == "0"
    failure = root.find("./testsuite/testcase/failure")
    assert failure is not None
    assert failure.attrib["message"] == "expected 200 got 500"


def test_error_outranks_failure() -> None:
    """A case with both an ERROR and a FAIL step counts as an error, not a failure."""
    xml = render_junit(
        "smoke",
        _steps(
            _Step("a", 1, StepOutcome.FAIL, 10, error_message="assertion failed"),
            _Step("a", 2, StepOutcome.ERROR, 10, error_message="connection refused"),
        ),
    )
    root = fromstring(xml)
    assert root.attrib["failures"] == "0"
    assert root.attrib["errors"] == "1"
    err = root.find("./testsuite/testcase/error")
    assert err is not None
    # First failing step's message wins (FAIL came first by step_order).
    assert err.attrib["message"] == "assertion failed"


def test_all_skipped_case_is_skipped() -> None:
    """ZERO-tier prose-only case: every step SKIP/PENDING → skipped testcase."""
    xml = render_junit(
        "smoke",
        _steps(
            _Step("a", 1, StepOutcome.SKIP, 0),
            _Step("a", 2, StepOutcome.PENDING, 0),
        ),
    )
    root = fromstring(xml)
    assert root.attrib["tests"] == "1"
    assert root.attrib["skipped"] == "1"
    assert root.find("./testsuite/testcase/skipped") is not None


def test_partial_skip_with_a_pass_is_not_skipped() -> None:
    xml = render_junit(
        "smoke",
        _steps(
            _Step("a", 1, StepOutcome.SKIP, 0),
            _Step("a", 2, StepOutcome.PASS, 30),
        ),
    )
    root = fromstring(xml)
    assert root.attrib["skipped"] == "0"
    case = root.find("./testsuite/testcase")
    assert case is not None
    assert list(case) == []  # passed


def test_multi_case_tally_and_order() -> None:
    xml = render_junit(
        "regression",
        _steps(
            _Step("a", 1, StepOutcome.PASS, 100),
            _Step("b", 1, StepOutcome.FAIL, 200, error_message="boom"),
            _Step("c", 1, StepOutcome.ERROR, 50, error_message="oops"),
            _Step("d", 1, StepOutcome.SKIP, 0),
        ),
    )
    root = fromstring(xml)
    assert root.attrib["tests"] == "4"
    assert root.attrib["failures"] == "1"
    assert root.attrib["errors"] == "1"
    assert root.attrib["skipped"] == "1"
    assert root.attrib["time"] == "0.350"
    names = [tc.attrib["name"] for tc in root.findall("./testsuite/testcase")]
    assert names == ["TC-a", "TC-b", "TC-c", "TC-d"]  # first-seen order preserved


def test_steps_sorted_by_order_within_case() -> None:
    """Out-of-order step rows still sum/verdict correctly (sorted by step_order)."""
    xml = render_junit(
        "smoke",
        _steps(
            _Step("a", 2, StepOutcome.FAIL, 50, error_message="second"),
            _Step("a", 1, StepOutcome.PASS, 100, error_message=None),
        ),
    )
    root = fromstring(xml)
    failure = root.find("./testsuite/testcase/failure")
    assert failure is not None
    assert failure.attrib["message"] == "second"
    assert root.find("./testsuite/testcase").attrib["time"] == "0.150"


def test_empty_run_is_valid_empty_suite() -> None:
    xml = render_junit("smoke", [])
    root = fromstring(xml)
    assert root.attrib["tests"] == "0"
    assert root.find("./testsuite") is not None
    assert root.findall("./testsuite/testcase") == []


def test_xml_escapes_special_chars_in_message() -> None:
    xml = render_junit(
        "smoke",
        _steps(_Step("a", 1, StepOutcome.FAIL, 10, error_message='<bad> & "quote"')),
    )
    # Parses without error → properly escaped.
    root = fromstring(xml)
    failure = root.find("./testsuite/testcase/failure")
    assert failure is not None
    assert failure.attrib["message"] == '<bad> & "quote"'
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
