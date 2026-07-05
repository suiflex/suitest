"""Failure-bundle serializer: smart excerpts, NOT a dump.

Consumer = an LLM/agent context window. Rules (spec P0 #4):
console -> error/warning only; network -> non-2xx only; DOM -> subtree around the
failed selector; total output is byte-budgeted (default 8 KB). Everything here is
a small pure function tested in isolation, plus one loader that reads the last
LOCAL run's output dir into ``FailedCase`` records.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_BODY_SNIPPET = 400
_FAIL_STATES = ("FAILED", "ERROR")


def excerpt_console(lines: list[dict], *, max_lines: int = 20) -> list[str]:
    kept = [
        f"[{line.get('level')}] {line.get('message', '')}"
        for line in lines
        if str(line.get("level", "")).lower() in ("error", "warning", "warn")
    ]
    return kept[-max_lines:]  # last = closest to the failure


def excerpt_network(entries: list[dict], *, max_entries: int = 10) -> list[str]:
    out: list[str] = []
    for entry in entries:
        try:
            status = int(entry.get("status", 0))
        except (TypeError, ValueError):
            status = 0
        # 2xx success and 3xx redirects are normal — only surface real failures.
        if 200 <= status < 400:
            continue
        line = f"{entry.get('method', '?')} {entry.get('url', '?')} -> {status}"
        body = str(entry.get("response_body", "")).strip()
        if body:
            line += f" — {body[:_BODY_SNIPPET]}"
        out.append(line)
    return out[-max_entries:]


def _selector_tokens(selector: str) -> list[str]:
    # "#submit-btn" -> ["submit", "btn"]; ".foo bar" -> ["foo", "bar"]
    return [t for t in re.split(r"[^a-zA-Z0-9]+", selector) if len(t) >= 3]


def excerpt_dom(dom: str, *, failed_selector: str, max_chars: int = 2000) -> str:
    """Clip DOM to the lines around the failed selector + similar candidates.

    ponytail: per-line token-overlap heuristic, not an HTML parser — upgrade to
    structural matching if the heuristic ever proves too coarse.
    """
    lines = dom.splitlines()
    tokens = _selector_tokens(failed_selector)
    if not tokens:
        return dom[:max_chars]

    hits = [
        i
        for i, line in enumerate(lines)
        if any(tok.lower() in line.lower() for tok in tokens)
    ]
    if not hits:
        return dom[:max_chars]

    hit_set = set(hits)
    keep: set[int] = set()
    for i in hits:
        keep.update(range(max(0, i - 2), min(len(lines), i + 3)))  # ±2 lines context
    out_lines: list[str] = []
    last = -10
    for i in sorted(keep):
        if i > last + 1:
            out_lines.append("…")
        text = lines[i].strip()
        # A single monster line (e.g. minified/huge attr) must not bury the match
        # or blow the budget. Clip context lines; keep the actual hit line longer.
        cap = 400 if i in hit_set else 120
        if len(text) > cap:
            text = text[:cap] + "…"
        out_lines.append(text)
        last = i
    return "\n".join(out_lines)[:max_chars]


@dataclass
class FailedCase:
    title: str
    failed_step_index: int
    total_steps: int
    step_description: str
    error_message: str
    error_stack: str = ""
    failed_selector: str = ""
    dom: str = ""
    console: list[dict] = field(default_factory=list)
    network: list[dict] = field(default_factory=list)
    evidence_links: dict[str, str] = field(default_factory=dict)
    classification: str = ""  # optional failure label (STALE/FLAKE/...) from run data


def build_failure_markdown(cases: list[FailedCase], *, budget_bytes: int = 8192) -> str:
    """Render failing cases to one budgeted markdown bundle (<= budget_bytes).

    The byte cap is HARD: the final slice is on the encoded bytes so multibyte
    content can never smuggle the output over budget.
    """
    if not cases:
        return ""
    per_case = max(1024, budget_bytes // max(1, len(cases)))
    sections = [_render_case(c, per_case) for c in cases]
    out = "\n\n---\n\n".join(sections)
    return out.encode()[:budget_bytes].decode(errors="ignore")


def _render_case(c: FailedCase, budget: int) -> str:
    dom_budget = budget // 3
    header = f"## Test: {c.title} — FAIL at step {c.failed_step_index}/{c.total_steps}"
    if c.classification:
        header += f" [{c.classification}]"
    parts = [
        header,
        f"**Step {c.failed_step_index}/{c.total_steps}**: {c.step_description}",
        f"**Error**: {c.error_message[:500]}",
    ]
    if c.dom:
        parts.append(
            "**DOM at failure** (excerpt):\n```html\n"
            + excerpt_dom(c.dom, failed_selector=c.failed_selector, max_chars=dom_budget)
            + "\n```"
        )
    console = excerpt_console(c.console)
    if console:
        parts.append("**Console** (error/warning only):\n" + "\n".join(console))
    network = excerpt_network(c.network)
    if network:
        parts.append("**Network** (failures only):\n" + "\n".join(network))
    if c.evidence_links:
        links = " · ".join(f"[{k}]({v})" for k, v in c.evidence_links.items())
        parts.append(f"**Evidence**: {links}")
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# Loader: last LOCAL run output dir -> list[FailedCase]
# --------------------------------------------------------------------------- #


def _inner_error(error: str) -> str:
    """Last non-empty traceback line = the actual message (e.g. 'TimeoutError: …')."""
    lines = [ln.strip() for ln in (error or "").splitlines() if ln.strip()]
    return lines[-1] if lines else (error or "").strip()


def _failed_step(steps: list[dict], total: int) -> tuple[int, str]:
    """First FAILED/ERROR step -> (index, description). Falls back to the last step."""
    for s in steps:
        if str(s.get("status", "")).upper() in _FAIL_STATES:
            return int(s.get("index", 0)), str(s.get("description", ""))
    if steps:
        last = steps[-1]
        return int(last.get("index", total)), str(last.get("description", ""))
    return total, ""


def _file_uri(mode_dir: Path, name: str) -> str | None:
    """Relative evidence file name -> absolute file:// URI, or None if it's gone.

    Missing evidence is skipped, never fatal — a partial bundle beats no bundle.
    """
    if not name:
        return None
    p = (mode_dir / name).resolve()
    return p.as_uri() if p.is_file() else None


def _evidence_links(result: dict, mode_dir: Path) -> dict[str, str]:
    links: dict[str, str] = {}
    shot = _file_uri(mode_dir, str(result.get("screenshot", "")))
    if shot:
        links["screenshot"] = shot
    video = _file_uri(mode_dir, str(result.get("video", "")))
    if video:
        links["video"] = video
    return links


def _context_sidecar(mode_dir: Path, test_id: str) -> dict:
    """Optional ``<TC>.context.json`` (dom/console/network/failedSelector).

    Written by the frontend recorder when the evidence-recording flag is on; the
    plain local run has none, so absence is normal — return {}.
    """
    p = mode_dir / f"{test_id}.context.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_failed_cases(output_dir: Path) -> list[FailedCase]:
    """Read the last LOCAL run's output dir into FailedCase records.

    Source of truth: ``reports/summary.json`` (== ``summary_to_json(RunSummary)``).
    Only FAILED/ERROR cases are returned. Evidence file names resolve to absolute
    ``file://`` URIs; a missing file drops that link rather than raising. DOM/
    console/network come from the optional ``<TC>.context.json`` sidecar when the
    recorder wrote one (server-sourced context is a follow-up, same FailedCase).
    """
    root = Path(output_dir)
    summary_json = root / "reports" / "summary.json"
    if not summary_json.is_file():
        return []
    try:
        summary = json.loads(summary_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(summary, dict):
        return []

    mode = str(summary.get("mode", "")).strip()
    mode_dir = root / mode if mode else root
    results = summary.get("results")
    if not isinstance(results, list):
        return []

    cases: list[FailedCase] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        if str(result.get("status", "")).upper() not in _FAIL_STATES:
            continue
        steps = [s for s in (result.get("steps") or []) if isinstance(s, dict)]
        total = len(steps) or 1
        step_index, step_desc = _failed_step(steps, total)
        ctx = _context_sidecar(mode_dir, str(result.get("testId", "")))
        cases.append(
            FailedCase(
                title=str(result.get("title") or result.get("testId") or "untitled"),
                failed_step_index=step_index,
                total_steps=total,
                step_description=step_desc,
                error_message=_inner_error(str(result.get("error", ""))),
                error_stack=str(result.get("error", "")),
                failed_selector=str(ctx.get("failedSelector", "")),
                dom=str(ctx.get("dom", "")),
                console=[c for c in (ctx.get("console") or []) if isinstance(c, dict)],
                network=[n for n in (ctx.get("network") or []) if isinstance(n, dict)],
                evidence_links=_evidence_links(result, mode_dir),
            )
        )
    return cases
