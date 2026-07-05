"""Tests for the failure-bundle serializer + local-run loader + MCP tool.

Serializer functions are PURE (Task 2-4). The loader reads the frozen real-run
fixture (Task 1). The tool wires it into the MCP envelope (Task 6).
"""

from __future__ import annotations

from pathlib import Path

from suitest_lifecycle.failure_context import (
    FailedCase,
    build_failure_markdown,
    excerpt_console,
    excerpt_dom,
    excerpt_network,
    load_failed_cases,
)

FIXTURE = Path(__file__).parent / "fixtures" / "failed_run" / "output"


def _case() -> FailedCase:
    return FailedCase(
        title="checkout-flow",
        failed_step_index=4,
        total_steps=7,
        step_description='click "#submit-btn"',
        error_message="TimeoutError: waiting for #submit-btn (30s)",
        error_stack="Trace: ...\n  at click ...",
        failed_selector="#submit-btn",
        dom="<form id='checkout'><button id='submit-button' disabled>Pay</button></form>",
        console=[{"level": "error", "message": "POST /api/cart 500"}],
        network=[
            {
                "method": "POST",
                "url": "/api/cart",
                "status": 500,
                "response_body": '{"error":"inventory timeout"}',
            }
        ],
        evidence_links={
            "screenshot": "file:///tmp/shot.png",
            "video": "file:///tmp/v.webm",
        },
    )

_DOM = """
<html><body>
<header><nav>menu very long here {filler}</nav></header>
<form id="checkout">
  <input name="qty" value="1">
  <button id="submit-button" disabled>Pay now</button>
</form>
<footer>copyright</footer>
</body></html>
""".replace("{filler}", "x" * 5000)


def test_console_keeps_only_error_and_warning() -> None:
    lines = [
        {"level": "info", "message": "app started"},
        {"level": "error", "message": "POST /api/cart 500"},
        {"level": "warning", "message": "deprecated API"},
        {"level": "debug", "message": "noise"},
    ]
    out = excerpt_console(lines, max_lines=20)
    assert out == ["[error] POST /api/cart 500", "[warning] deprecated API"]


def test_console_caps_line_count() -> None:
    lines = [{"level": "error", "message": f"e{i}"} for i in range(100)]
    out = excerpt_console(lines, max_lines=10)
    assert len(out) == 10
    assert out[-1] == "[error] e99"  # keep the LAST (closest to the failure)


def test_network_keeps_only_non_2xx() -> None:
    entries = [
        {"method": "GET", "url": "/ok", "status": 200},
        {
            "method": "POST",
            "url": "/api/cart",
            "status": 500,
            "response_body": '{"error": "inventory timeout"}',
        },
        {"method": "GET", "url": "/redirect", "status": 302},
    ]
    out = excerpt_network(entries, max_entries=10)
    assert len(out) == 1
    assert "POST /api/cart -> 500" in out[0]
    assert "inventory timeout" in out[0]


def test_network_truncates_huge_response_body() -> None:
    entries = [
        {"method": "POST", "url": "/x", "status": 500, "response_body": "A" * 10_000}
    ]
    out = excerpt_network(entries, max_entries=10)
    assert len(out[0]) < 600  # body clipped, not carried whole


def test_dom_excerpt_contains_area_around_failed_selector() -> None:
    out = excerpt_dom(_DOM, failed_selector="#submit-btn", max_chars=2000)
    # exact selector absent — similar candidate (token overlap 'submit') MUST show
    assert "submit-button" in out
    assert len(out) <= 2000
    assert "xxxxx" not in out  # filler far from the selector is not carried


def test_dom_excerpt_exact_match_included() -> None:
    out = excerpt_dom(_DOM, failed_selector="#checkout", max_chars=2000)
    assert 'id="checkout"' in out


def test_dom_excerpt_no_selector_returns_head_slice() -> None:
    out = excerpt_dom(_DOM, failed_selector="", max_chars=500)
    assert len(out) <= 500


def test_markdown_contains_all_sections() -> None:
    md = build_failure_markdown([_case()])
    assert "## Test: checkout-flow" in md
    assert "step 4/7" in md
    assert "TimeoutError" in md
    assert "submit-button" in md  # DOM excerpt
    assert "POST /api/cart -> 500" in md  # network
    assert "[error] POST /api/cart 500" in md  # console
    assert "file:///tmp/shot.png" in md  # evidence link


def test_markdown_respects_total_budget() -> None:
    huge = _case()
    huge.dom = "<div class='submit'>" + "y" * 100_000 + "</div>"
    huge.console = [{"level": "error", "message": "e" * 500} for _ in range(500)]
    md = build_failure_markdown([huge], budget_bytes=8192)
    assert len(md.encode()) <= 8192


def test_multiple_failures_all_present_within_budget() -> None:
    md = build_failure_markdown([_case(), _case()], budget_bytes=8192)
    assert md.count("## Test:") == 2
    assert len(md.encode()) <= 8192


def test_load_failed_cases_from_local_output() -> None:
    cases = load_failed_cases(FIXTURE)
    assert len(cases) == 1  # only TC002 failed; TC001 passed
    c = cases[0]
    assert c.title  # case title populated
    assert "TimeoutError" in c.error_message  # inner message, not the raw trace
    assert c.total_steps == 4
    assert c.failed_step_index == 3  # the FAILED step in the sidecar
    assert "click #submit-btn" in c.step_description
    # context sidecar wired through
    assert c.failed_selector == "#submit-btn"
    assert "submit-button" in c.dom
    assert any("500" in n for n in excerpt_network(c.network))
    assert any("error" in str(line.get("level")) for line in c.console)
    # evidence -> absolute file:// URIs that actually resolve
    assert "screenshot" in c.evidence_links
    assert c.evidence_links["screenshot"].startswith("file://")


def test_load_failed_cases_missing_output_dir() -> None:
    # No prior run at all -> empty list, never raises.
    assert load_failed_cases(Path("/nonexistent/suitest/output")) == []


def test_full_bundle_from_fixture_within_budget() -> None:
    # End-to-end: real fixture -> loader -> markdown, hard 8 KB budget holds.
    md = build_failure_markdown(load_failed_cases(FIXTURE))
    assert "## Test:" in md
    assert "#submit-btn" in md or "submit-button" in md
    assert len(md.encode()) <= 8192
