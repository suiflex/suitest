"""Unit tests for ``suitest_agent.generators.diff_selector`` (M6-1).

All tests are deterministic — no DB, no network.  The LLM path is exercised
via :class:`MockProvider`.

Coverage:
  - ``parse_diff``: empty input, single-file diff, multi-file diff, function
    extraction (added + removed), edge cases (deletion markers, /dev/null).
  - ``select_relevant_cases``: LLM happy path, LLM returns empty selection
    (full-suite fallback), LLM returns invalid JSON (full-suite fallback),
    empty available_cases, empty changed_files.
  - M6-2 timing assertion: selecting 100 cases from a 10-file diff completes
    in < 1 second (pure-Python parse is O(lines), LLM path is async-mocked
    and never blocks).
"""

from __future__ import annotations

import json
import time

import pytest
from suitest_agent.generators.diff_selector import (
    CaseSummary,
    ChangedFile,
    parse_diff,
    select_relevant_cases,
)
from suitest_agent.providers.base import CompletionResult
from suitest_agent.providers.mock import MockProvider

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_SIMPLE_DIFF = """\
diff --git a/src/auth.py b/src/auth.py
index aaa..bbb 100644
--- a/src/auth.py
+++ b/src/auth.py
@@ -10,6 +10,8 @@
 def existing_func():
     pass

+def new_login_handler(user, password):
+    return authenticate(user, password)
+
 def another():
     pass
"""

_MULTI_FILE_DIFF = """\
diff --git a/src/auth.py b/src/auth.py
--- a/src/auth.py
+++ b/src/auth.py
@@ -1,3 +1,4 @@
+def login(user, pwd):
     pass

diff --git a/src/checkout.py b/src/checkout.py
--- a/src/checkout.py
+++ b/src/checkout.py
@@ -5,3 +5,5 @@
 pass
+def process_payment(card):
+    return True
"""

_REMOVED_FUNC_DIFF = """\
--- a/src/legacy.py
+++ b/src/legacy.py
@@ -1,4 +1,2 @@
-def old_validate(token):
-    pass
 def keep():
     pass
"""


def _mock_with_ids(ids: list[str], rationale: str = "test selection") -> MockProvider:
    payload = json.dumps({"selected_ids": ids, "rationale": rationale})
    return MockProvider(
        scripted=[CompletionResult(content=payload, model="mock-1", tokens_in=5, tokens_out=10)]
    )


def _case(case_id: str, name: str) -> CaseSummary:
    return CaseSummary(
        id=case_id,
        public_id=f"TC-{case_id}",
        name=name,
        step_summary=f"open {name} page and verify",
    )


# ---------------------------------------------------------------------------
# parse_diff tests
# ---------------------------------------------------------------------------


def test_parse_diff_empty_string_returns_empty() -> None:
    assert parse_diff("") == []


def test_parse_diff_whitespace_only_returns_empty() -> None:
    assert parse_diff("   \n\n  ") == []


def test_parse_diff_single_file_path_extracted() -> None:
    result = parse_diff(_SIMPLE_DIFF)
    assert len(result) == 1
    assert result[0].path == "src/auth.py"


def test_parse_diff_added_lines_tracked() -> None:
    result = parse_diff(_SIMPLE_DIFF)
    assert len(result[0].changed_lines) > 0


def test_parse_diff_added_function_detected() -> None:
    result = parse_diff(_SIMPLE_DIFF)
    assert "new_login_handler" in result[0].added_functions


def test_parse_diff_multi_file() -> None:
    result = parse_diff(_MULTI_FILE_DIFF)
    paths = [f.path for f in result]
    assert "src/auth.py" in paths
    assert "src/checkout.py" in paths


def test_parse_diff_multi_file_functions_per_file() -> None:
    result = parse_diff(_MULTI_FILE_DIFF)
    auth_file = next(f for f in result if f.path == "src/auth.py")
    checkout_file = next(f for f in result if f.path == "src/checkout.py")
    assert "login" in auth_file.added_functions
    assert "process_payment" in checkout_file.added_functions


def test_parse_diff_removed_function_detected() -> None:
    result = parse_diff(_REMOVED_FUNC_DIFF)
    assert len(result) == 1
    assert "old_validate" in result[0].removed_functions


def test_parse_diff_dev_null_excluded() -> None:
    diff = """\
--- /dev/null
+++ b/src/newfile.py
@@ -0,0 +1,2 @@
+def brand_new():
+    pass
"""
    result = parse_diff(diff)
    assert len(result) == 1
    assert result[0].path == "src/newfile.py"
    assert "brand_new" in result[0].added_functions


def test_parse_diff_deletion_only_file_excluded() -> None:
    diff = """\
--- a/src/old.py
+++ /dev/null
@@ -1,3 +0,0 @@
-def gone():
-    pass
"""
    result = parse_diff(diff)
    # /dev/null path is stripped → file with empty path is filtered out
    assert all(f.path != "" for f in result)


def test_parse_diff_no_functions_still_tracks_lines() -> None:
    diff = """\
--- a/config.yaml
+++ b/config.yaml
@@ -1,2 +1,3 @@
 key: value
+new_key: new_value
 other: thing
"""
    result = parse_diff(diff)
    assert len(result) == 1
    assert result[0].added_functions == []
    assert len(result[0].changed_lines) == 1


# ---------------------------------------------------------------------------
# select_relevant_cases tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_returns_llm_selection() -> None:
    cases = [_case("aaa", "Login"), _case("bbb", "Checkout"), _case("ccc", "Profile")]
    changed = [ChangedFile(path="src/auth.py", added_functions=["login"])]
    provider = _mock_with_ids(["aaa"], "auth changed")

    result = await select_relevant_cases(changed, cases, provider, model="mock-1")

    assert result.tier_used == "llm"
    assert result.selected_case_ids == ["aaa"]
    assert result.rationale  # rationale is non-empty


@pytest.mark.asyncio
async def test_select_all_case_ids_always_populated() -> None:
    cases = [_case("x1", "A"), _case("x2", "B")]
    changed = [ChangedFile(path="src/foo.py")]
    provider = _mock_with_ids(["x1"])

    result = await select_relevant_cases(changed, cases, provider, model="mock-1")

    assert set(result.all_case_ids) == {"x1", "x2"}


@pytest.mark.asyncio
async def test_select_empty_cases_returns_empty() -> None:
    changed = [ChangedFile(path="src/auth.py")]
    result = await select_relevant_cases(changed, [], MockProvider(), model="mock-1")

    assert result.selected_case_ids == []
    assert result.all_case_ids == []
    assert result.tier_used == "llm"


@pytest.mark.asyncio
async def test_select_empty_diff_returns_full_suite() -> None:
    cases = [_case("y1", "A"), _case("y2", "B")]
    result = await select_relevant_cases([], cases, MockProvider(), model="mock-1")

    assert result.selected_case_ids == ["y1", "y2"]
    assert "empty diff" in result.rationale.lower()


@pytest.mark.asyncio
async def test_select_llm_empty_selection_falls_back_to_full_suite() -> None:
    """LLM returns an empty selected_ids list → full-suite fallback."""
    cases = [_case("z1", "A"), _case("z2", "B")]
    changed = [ChangedFile(path="src/x.py")]
    provider = _mock_with_ids([])  # deliberate empty selection

    result = await select_relevant_cases(changed, cases, provider, model="mock-1")

    assert set(result.selected_case_ids) == {"z1", "z2"}


@pytest.mark.asyncio
async def test_select_llm_invalid_json_falls_back_to_full_suite() -> None:
    """LLM returns non-JSON → exception caught → full-suite fallback."""
    cases = [_case("q1", "A"), _case("q2", "B")]
    changed = [ChangedFile(path="src/y.py")]
    bad_provider = MockProvider(
        scripted=[
            CompletionResult(
                content="not valid json at all", model="mock-1", tokens_in=1, tokens_out=1
            )
        ]
    )

    result = await select_relevant_cases(changed, cases, bad_provider, model="mock-1")

    assert set(result.selected_case_ids) == {"q1", "q2"}
    assert "precaution" in result.rationale.lower()


@pytest.mark.asyncio
async def test_select_filters_out_unknown_ids() -> None:
    """LLM hallucinated an id that does not exist in available_cases → filtered."""
    cases = [_case("real1", "A"), _case("real2", "B")]
    changed = [ChangedFile(path="src/z.py")]
    provider = _mock_with_ids(["real1", "ghost_id_not_in_cases"])

    result = await select_relevant_cases(changed, cases, provider, model="mock-1")

    assert "ghost_id_not_in_cases" not in result.selected_case_ids
    assert "real1" in result.selected_case_ids


@pytest.mark.asyncio
async def test_select_llm_markdown_fence_stripped() -> None:
    """LLM wraps response in ```json ... ``` — fences are stripped before parse."""
    cases = [_case("m1", "X")]
    changed = [ChangedFile(path="a.py")]
    payload = "```json\n" + json.dumps({"selected_ids": ["m1"], "rationale": "fenced"}) + "\n```"
    fenced_provider = MockProvider(
        scripted=[CompletionResult(content=payload, model="mock-1", tokens_in=1, tokens_out=1)]
    )

    result = await select_relevant_cases(changed, cases, fenced_provider, model="mock-1")

    assert result.selected_case_ids == ["m1"]


# ---------------------------------------------------------------------------
# M6-2 timing assertion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_selection_under_one_second_for_100_cases() -> None:
    """M6-2: selecting from 100 cases over a 10-file diff finishes in < 1 s.

    The LLM call is mocked (no network); the timing assertion covers the
    pure-Python parse + prompt-build + result-assembly path.
    """
    # Build 10-file synthetic diff.
    lines: list[str] = []
    for i in range(10):
        lines += [
            f"--- a/src/module_{i}.py",
            f"+++ b/src/module_{i}.py",
            "@@ -1,2 +1,4 @@",
            f"+def handler_{i}(req):",
            f"+    return process_{i}(req)",
            " pass",
        ]
    diff = "\n".join(lines)

    cases = [_case(f"case_{j:03d}", f"Test case {j}") for j in range(100)]
    selected_subset = [f"case_{j:03d}" for j in range(10)]
    provider = _mock_with_ids(selected_subset, "10 most relevant")

    t0 = time.monotonic()
    result = await select_relevant_cases(parse_diff(diff), cases, provider, model="mock-1")
    elapsed = time.monotonic() - t0

    assert elapsed < 1.0, f"diff selection took {elapsed:.3f}s — expected < 1s"
    assert len(result.selected_case_ids) == 10
    assert result.tier_used == "llm"
