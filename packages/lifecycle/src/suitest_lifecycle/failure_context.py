"""Failure-bundle serializer: smart excerpts, NOT a dump.

Consumer = an LLM/agent context window. Rules (spec P0 #4):
console -> error/warning only; network -> non-2xx only; DOM -> subtree around the
failed selector; total output is byte-budgeted (default 8 KB). Everything here is
a small pure function tested in isolation, plus one loader that reads the last
LOCAL run's output dir into ``FailedCase`` records.
"""

from __future__ import annotations

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
