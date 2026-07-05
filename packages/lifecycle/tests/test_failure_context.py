"""Tests for the failure-bundle serializer + local-run loader + MCP tool.

Serializer functions are PURE (Task 2-4). The loader reads the frozen real-run
fixture (Task 1). The tool wires it into the MCP envelope (Task 6).
"""

from __future__ import annotations

from suitest_lifecycle.failure_context import (
    excerpt_console,
    excerpt_dom,
    excerpt_network,
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
