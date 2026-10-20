from __future__ import annotations

import base64

from suitest_mcp.models import McpToolResult
from suitest_runner.executors.tiny_ocr import (
    build_tiny_ocr_solve_script,
    classify_ocr_output,
    evaluate_math_expression,
    load_ocrad_source,
    parse_browser_eval_result,
)


def test_load_ocrad_source() -> None:
    source = load_ocrad_source()
    assert len(source) > 500_000
    assert "OCRAD" in source


def test_evaluate_math_expression() -> None:
    assert evaluate_math_expression("12 + 5 = ?") == 17
    assert evaluate_math_expression("12+5") == 17
    assert evaluate_math_expression("20 - 8 = ?") == 12
    assert evaluate_math_expression("6 x 7 = ?") == 42
    assert evaluate_math_expression("6 * 7") == 42
    assert evaluate_math_expression("40 / 5 = ?") == 8
    assert evaluate_math_expression("10 / 0 = ?") is None
    assert evaluate_math_expression("KAPUAS") is None
    assert evaluate_math_expression("") is None


def test_classify_ocr_output() -> None:
    # Math expression
    math_res = classify_ocr_output("15 + 4 = ?")
    assert math_res["status"] == "solved"
    assert math_res["text"] == "19"
    assert math_res["source"] == "local_math"

    # Clean alphanumeric
    alpha_res = classify_ocr_output("KAPUAS\n")
    assert alpha_res["status"] == "solved"
    assert alpha_res["text"] == "KAPUAS"
    assert alpha_res["source"] == "tiny_ocr"

    # Ambiguous or short
    short_res = classify_ocr_output("ab1")
    assert short_res["status"] == "fallback"
    assert short_res["reason"] == "text_too_short_or_ambiguous"

    # Empty
    empty_res = classify_ocr_output("")
    assert empty_res["status"] == "fallback"
    assert empty_res["reason"] == "empty_text"


def test_build_tiny_ocr_solve_script() -> None:
    script = build_tiny_ocr_solve_script("img#captcha", 'page.frameLocator("iframe")')
    assert 'locator("img#captcha")' in script
    assert 'page.frameLocator("iframe")' in script
    assert "OCRAD" in script
    assert "avgBgVariance" in script
    assert "screenshot" in script


def test_parse_browser_eval_result_solved() -> None:
    snap_result = McpToolResult(
        ok=True,
        output={"status": "solved", "text": "GUNUNGMAS", "source": "tiny_ocr"},
        stdout="",
        duration_ms=15,
    )
    text, image_bytes = parse_browser_eval_result(snap_result)
    assert text == "GUNUNGMAS"
    assert image_bytes is None


def test_parse_browser_eval_result_fallback() -> None:
    raw_bytes = b"real-image-bytes"
    b64 = "data:image/png;base64," + base64.b64encode(raw_bytes).decode("ascii")
    snap_result = McpToolResult(
        ok=True,
        output={"status": "fallback", "reason": "high_noise", "image_base64": b64},
        stdout="",
        duration_ms=25,
    )
    text, image_bytes = parse_browser_eval_result(snap_result)
    assert text is None
    assert image_bytes == raw_bytes


def test_parse_browser_eval_result_playwright_mcp_markdown() -> None:
    stdout = """### Result
{"status": "solved", "text": "KAPUAS", "source": "tiny_ocr"}
### Ran Playwright code:
async (page) => { ... }
"""
    snap_result = McpToolResult(
        ok=True,
        output={},
        stdout=stdout,
        duration_ms=30,
    )
    text, image_bytes = parse_browser_eval_result(snap_result)
    assert text == "KAPUAS"
    assert image_bytes is None


def test_parse_browser_eval_result_legacy_raw_b64() -> None:
    raw_bytes = b"legacy-screenshot"
    b64 = base64.b64encode(raw_bytes).decode("ascii")
    snap_result = McpToolResult(
        ok=True,
        output={"result": b64},
        stdout="",
        duration_ms=20,
    )
    text, image_bytes = parse_browser_eval_result(snap_result)
    assert text is None
    assert image_bytes == raw_bytes
