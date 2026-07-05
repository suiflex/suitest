"""Failure-bundle serializer: smart excerpts, NOT a dump.

Consumer = an LLM/agent context window. Rules (spec P0 #4):
console -> error/warning only; network -> non-2xx only; DOM -> subtree around the
failed selector; total output is byte-budgeted (default 8 KB). Everything here is
a small pure function tested in isolation, plus one loader that reads the last
LOCAL run's output dir into ``FailedCase`` records.
"""

from __future__ import annotations

import re

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
