"""PR comment renderer — markdown murni, tidak tahu forge (GitHub/GitLab/dst)."""

from __future__ import annotations

# marker upsert: publisher forge mana pun mencari string ini utk update comment lama
COMMENT_MARKER = "<!-- suitest-report -->"

_EXCERPT_LIMIT = 1500  # per failing case di comment; bundle penuh via get_failure_context


def render_pr_comment(
    *,
    cases: list[dict],
    passed: int,
    failed: int,
    duration_ms: int | None,
    dashboard_url: str,
) -> str:
    total = passed + failed
    icon = "✅" if failed == 0 else "❌"
    duration = f" in {duration_ms / 1000:.0f}s" if duration_ms else ""
    lines = [
        COMMENT_MARKER,
        f"## Suitest — {passed}/{total} passed {icon}{duration}",
        "",
        "| Case | Status | Evidence |",
        "|------|--------|----------|",
    ]
    for c in cases:
        status = "✅" if c.get("status") == "PASS" else "❌"
        ev = c.get("evidence_url", "")
        ev_cell = f"[view]({ev})" if ev else "—"
        lines.append(f"| {c['title']} | {status} | {ev_cell} |")

    failures = [c for c in cases if c.get("status") != "PASS" and c.get("failure_excerpt")]
    if failures:
        lines += ["", "<details><summary>Failure detail</summary>", ""]
        for c in failures:
            lines += [
                f"### {c['title']}",
                "```",
                str(c["failure_excerpt"])[:_EXCERPT_LIMIT],
                "```",
                "",
            ]
        lines.append("</details>")

    if dashboard_url:
        lines += ["", f"[Full report & videos]({dashboard_url})"]
    return "\n".join(lines)
