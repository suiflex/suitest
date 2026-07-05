"""Failure-bundle serializer: smart excerpts, NOT a dump.

Consumer = an LLM/agent context window. Rules (spec P0 #4):
console -> error/warning only; network -> non-2xx only; DOM -> subtree around the
failed selector; total output is byte-budgeted (default 8 KB). Everything here is
a small pure function tested in isolation, plus one loader that reads the last
LOCAL run's output dir into ``FailedCase`` records.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_BODY_SNIPPET = 400


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
