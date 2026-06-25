"""Git diff parser and LLM-driven impact analyser (M6-1).

Two public surfaces:

1. :func:`parse_diff` — pure Python, ZERO-compatible, no LLM.
   Converts a unified diff string into a list of :class:`ChangedFile` objects.

2. :func:`select_relevant_cases` — CLOUD/LOCAL only (caller must gate).
   Given changed files + available test-case summaries, asks the LLM which
   cases are worth running for this PR and returns a :class:`DiffSelectionResult`.

Design notes:
  - ``parse_diff`` has no side effects and holds no state.  It is safe to call
    at ZERO tier; the service layer calls it before the tier branch.
  - ``select_relevant_cases`` intentionally takes a :class:`LLMProvider`
    (Protocol) so the test suite can inject :class:`MockProvider` without any
    network or env var.
  - Both return types are plain Pydantic models so callers can serialise
    straight to the API response without extra mapping.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, Field

from suitest_agent.providers.base import ChatMessage, ModelCall

if TYPE_CHECKING:
    from suitest_agent.providers.base import LLMProvider

# ---------------------------------------------------------------------------
# Regex helpers for unified diff parsing
# ---------------------------------------------------------------------------

_HUNK_HEADER_RE: Final = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_FUNC_DEF_RE: Final = re.compile(
    r"^[+-][ \t]*"
    r"(?:"
    # Python: def foo(...) / async def foo(...)
    r"(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\("
    r"|"
    # JS/TS: function foo(...) / async function foo(...)
    r"(?:async\s+)?function\s+([A-Za-z_$]\w*)\s*\("
    r"|"
    # Arrow / class method: foo(...) { or foo = (...) =>
    r"([A-Za-z_$]\w*)\s*(?:\([^)]*\)\s*\{|\s*=\s*(?:async\s+)?\([^)]*\)\s*=>)"
    r")",
)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ChangedFile(BaseModel):
    """One file's change summary extracted from a unified diff."""

    path: str
    changed_lines: list[int] = Field(default_factory=list)
    added_functions: list[str] = Field(default_factory=list)
    removed_functions: list[str] = Field(default_factory=list)


class CaseSummary(BaseModel):
    """Lightweight test-case representation sent to the LLM for relevance scoring."""

    id: str
    public_id: str
    name: str
    step_summary: str  # first 200 chars of all step actions concatenated


class DiffSelectionResult(BaseModel):
    """Result of a diff-selection run."""

    selected_case_ids: list[str]
    rationale: str
    all_case_ids: list[str]  # full set; caller uses this at ZERO tier
    tier_used: str  # "llm" | "fallback_full"


# ---------------------------------------------------------------------------
# Diff parser (pure, ZERO-compatible)
# ---------------------------------------------------------------------------


def parse_diff(diff_text: str) -> list[ChangedFile]:
    """Parse a unified diff string into a list of :class:`ChangedFile` objects.

    Handles multi-file diffs.  ``diff_text`` that is empty or contains no
    recognisable ``+++`` headers returns an empty list (not an error).

    Only ``+++`` lines (the new/updated file path) are used for file names;
    ``---`` lines (the original path) are intentionally ignored.

    Changed line numbers correspond to the *new* file position (from the
    ``+N,M`` hunk header) so callers can cross-reference against test step
    line annotations.
    """
    if not diff_text or not diff_text.strip():
        return []

    files: list[ChangedFile] = []
    current: ChangedFile | None = None
    new_line_cursor: int = 0

    for line in diff_text.splitlines():
        # ---- File header ---------------------------------------------------
        if line.startswith("+++ "):
            raw_path = line[4:]
            # Strip trailing timestamp that `diff -u` may append.
            raw_path = re.sub(r"\s+\d{4}-\d{2}-\d{2}.*$", "", raw_path)
            # Strip the b/ prefix that git adds.
            if raw_path.startswith("b/"):
                raw_path = raw_path[2:]
            path = raw_path.strip()
            if path == "/dev/null":
                path = ""
            current = ChangedFile(path=path)
            files.append(current)
            new_line_cursor = 0
            continue

        if line.startswith("--- "):
            # The --- line precedes +++; we wait for +++ to create ChangedFile.
            continue

        if current is None:
            continue

        # ---- Hunk header ---------------------------------------------------
        hunk_m = _HUNK_HEADER_RE.match(line)
        if hunk_m:
            new_line_cursor = int(hunk_m.group(1))
            continue

        # ---- Content lines -------------------------------------------------
        if line.startswith("+") and not line.startswith("+++"):
            current.changed_lines.append(new_line_cursor)
            new_line_cursor += 1
            func_m = _FUNC_DEF_RE.match(line)
            if func_m:
                fn_name = func_m.group(1) or func_m.group(2) or func_m.group(3) or ""
                if fn_name and fn_name not in current.added_functions:
                    current.added_functions.append(fn_name)

        elif line.startswith("-") and not line.startswith("---"):
            # Removed lines do NOT advance the new-file cursor.
            func_m = _FUNC_DEF_RE.match(line)
            if func_m:
                fn_name = func_m.group(1) or func_m.group(2) or func_m.group(3) or ""
                if fn_name and fn_name not in current.removed_functions:
                    current.removed_functions.append(fn_name)

        elif not line.startswith("\\"):
            # Context line (space-prefixed or blank) — advances new-file cursor.
            new_line_cursor += 1

    return [f for f in files if f.path]


# ---------------------------------------------------------------------------
# LLM selector (CLOUD/LOCAL only — caller must enforce tier gate)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT: Final = """\
You are a test-selection assistant for a software quality platform called Suitest.
Your task: given a list of changed source files (with their modified functions) and
a list of test cases (each with a short step summary), identify which test cases are
most likely to catch regressions introduced by these changes.

Respond with ONLY a valid JSON object — no markdown fences, no prose outside the object:
{
  "selected_ids": ["<case_id>", ...],
  "rationale": "<one sentence explaining the selection>"
}

Be conservative: prefer over-selecting to under-selecting.
If no test cases are clearly relevant, return all provided case ids.
"""

_MAX_CHANGED_FILES_IN_PROMPT: Final = 30
_MAX_CASES_IN_PROMPT: Final = 200


def _build_user_message(
    changed_files: list[ChangedFile],
    available_cases: list[CaseSummary],
) -> str:
    """Format the user turn sent to the LLM for diff-based case selection."""
    files_part: list[dict[str, object]] = []
    for cf in changed_files[:_MAX_CHANGED_FILES_IN_PROMPT]:
        entry: dict[str, object] = {"path": cf.path}
        if cf.added_functions:
            entry["added_functions"] = cf.added_functions
        if cf.removed_functions:
            entry["removed_functions"] = cf.removed_functions
        if cf.changed_lines:
            entry["changed_line_count"] = len(cf.changed_lines)
        files_part.append(entry)

    cases_part = [
        {
            "id": c.id,
            "public_id": c.public_id,
            "name": c.name,
            "step_summary": c.step_summary[:200],
        }
        for c in available_cases[:_MAX_CASES_IN_PROMPT]
    ]

    return json.dumps(
        {"changed_files": files_part, "test_cases": cases_part},
        ensure_ascii=False,
        indent=2,
    )


async def select_relevant_cases(
    changed_files: list[ChangedFile],
    available_cases: list[CaseSummary],
    provider: LLMProvider,
    *,
    model: str = "mock-1",
) -> DiffSelectionResult:
    """Ask the LLM which test cases are relevant for the given diff.

    CLOUD/LOCAL only — callers MUST have already enforced tier gating.

    When the LLM returns unparseable JSON or an empty selection the function
    falls back to ALL case ids so no coverage is accidentally lost.

    ``model`` is the LiteLLM model id resolved from the active
    :class:`~suitest_db.models.llm_config.LLMConfig`.
    """
    all_ids = [c.id for c in available_cases]

    if not available_cases:
        return DiffSelectionResult(
            selected_case_ids=[],
            rationale="No test cases available in the suite.",
            all_case_ids=[],
            tier_used="llm",
        )

    if not changed_files:
        return DiffSelectionResult(
            selected_case_ids=all_ids,
            rationale="Empty diff — returning full suite as a precaution.",
            all_case_ids=all_ids,
            tier_used="llm",
        )

    user_msg = _build_user_message(changed_files, available_cases)
    call = ModelCall(
        model=model,
        messages=[
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(role="user", content=user_msg),
        ],
        temperature=0.0,
        max_tokens=1024,
        cache_control=False,
    )

    try:
        result = await provider.complete(call)
        raw = result.content.strip()
        # Strip accidental markdown code fences.
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        parsed: dict[str, object] = json.loads(raw)
        raw_ids = parsed.get("selected_ids")
        selected_ids: list[str] = [str(i) for i in raw_ids] if isinstance(raw_ids, list) else []
        rationale: str = str(parsed.get("rationale") or "LLM selection")

        # Guard: keep only ids that actually exist in available_cases.
        valid_set = set(all_ids)
        selected_ids = [i for i in selected_ids if i in valid_set]

        if not selected_ids:
            selected_ids = all_ids
            rationale = (
                f"LLM returned empty selection — defaulting to full suite. "
                f"Original rationale: {rationale}"
            )

    except Exception:
        selected_ids = all_ids
        rationale = "LLM selection failed — returning full suite as a precaution."

    return DiffSelectionResult(
        selected_case_ids=selected_ids,
        rationale=rationale,
        all_case_ids=all_ids,
        tier_used="llm",
    )
