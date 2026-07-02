"""Human + machine readable reports.

Writes:
  * ``tmp/raw_report.md``     — TestSprite-style per-test report (metadata,
    requirement validation, coverage, gaps/risks).
  * ``reports/summary.json``  — machine summary for CI.
  * ``reports/summary.md``    — cross-mode rollup developers/QA/PO can skim.
  * ``reports/summary.html``  — standalone styled page (no external assets).
"""

from __future__ import annotations

import json

from suitest_lifecycle.models import RunSummary, TestOutcome, TestResult
from suitest_lifecycle.paths import Paths
from suitest_lifecycle.serialize import summary_to_json

_BADGE = {
    TestOutcome.PASSED: "✅ Passed",
    TestOutcome.FAILED: "❌ Failed",
    TestOutcome.SKIPPED: "⏭️ Skipped",
    TestOutcome.ERROR: "🔥 Error",
}


def _gaps(summary: RunSummary) -> list[str]:
    gaps: list[str] = []
    if not summary.ready:
        gaps.append(
            f"Target never became ready ({summary.ready_detail}); tests could not run reliably."
        )
    failed = [r for r in summary.results if r.status in (TestOutcome.FAILED, TestOutcome.ERROR)]
    for r in failed:
        first = (r.error or "").splitlines()[-1] if r.error else "no error captured"
        gaps.append(f"{r.test_id} {r.title}: {first}")
    if not gaps:
        gaps.append("No gaps detected — all generated requirements passed.")
    return gaps


def write_raw_report(summary: RunSummary, paths: Paths, date: str) -> None:
    lines: list[str] = []
    lines.append("# Suitest Testing Report")
    lines.append("")
    lines.append("## 1️⃣ Document Metadata")
    lines.append(f"- **Project:** {summary.project}")
    lines.append(f"- **Mode:** {summary.mode.value}")
    lines.append(f"- **Base URL:** {summary.base_url}")
    lines.append(f"- **Date:** {date}")
    lines.append("- **Prepared by:** Suitest")
    lines.append(
        f"- **Summary:** {summary.total} tests — {summary.passed} passed, "
        f"{summary.failed} failed, {summary.skipped} skipped, {summary.errored} error "
        f"({summary.duration_ms} ms)"
    )
    lines.append(
        f"- **Readiness:** {'ready' if summary.ready else 'NOT READY'} ({summary.ready_detail})"
    )
    lines.append("")
    lines.append("## 2️⃣ Requirement Validation Summary")
    for r in summary.results:
        lines.append("")
        lines.append(f"### {r.test_id} {r.title}")
        lines.append(f"- **Status:** {_BADGE[r.status]}")
        lines.append(f"- **Description:** {r.description}")
        lines.append(f"- **Duration:** {r.duration_ms} ms")
        if r.automation_file:
            lines.append(f"- **Automation:** `{r.automation_file}`")
        if r.error:
            lines.append("- **Error:**")
            lines.append("```")
            lines.extend(r.error.splitlines())
            lines.append("```")
    lines.append("")
    lines.append("## 3️⃣ Coverage & Matching Metrics")
    pct = (summary.passed / summary.total * 100) if summary.total else 0.0
    lines.append(f"- Pass rate: **{pct:.0f}%** ({summary.passed}/{summary.total})")
    by_cat = _coverage_by_outcome(summary.results)
    lines.append("")
    lines.append("| Outcome | Count |")
    lines.append("|---------|-------|")
    for name, count in by_cat:
        lines.append(f"| {name} | {count} |")
    lines.append("")
    lines.append("## 4️⃣ Key Gaps / Risks")
    for g in _gaps(summary):
        lines.append(f"- {g}")
    lines.append("")
    paths.raw_report_md.write_text("\n".join(lines), encoding="utf-8")


def _coverage_by_outcome(results: list[TestResult]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status.value] = counts.get(r.status.value, 0) + 1
    return sorted(counts.items())


def write_summary_json(summary: RunSummary, paths: Paths) -> None:
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    payload = summary_to_json(summary)
    (paths.reports_dir / "summary.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def write_summary_md(summary: RunSummary, paths: Paths) -> None:
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    pct = (summary.passed / summary.total * 100) if summary.total else 0.0
    lines = [
        f"# Suitest Summary — {summary.project}",
        "",
        f"- Mode: **{summary.mode.value}** · Base URL: `{summary.base_url}`",
        f"- Ready: **{'yes' if summary.ready else 'NO'}** ({summary.ready_detail})",
        f"- Result: **{summary.passed}/{summary.total} passed ({pct:.0f}%)** in {summary.duration_ms} ms",
        f"- Failed: {summary.failed} · Skipped: {summary.skipped} · Error: {summary.errored}",
        "",
        "| Test | Status | ms |",
        "|------|--------|----|",
    ]
    for r in summary.results:
        lines.append(f"| {r.test_id} {r.title} | {_BADGE[r.status]} | {r.duration_ms} |")
    (paths.reports_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary_html(summary: RunSummary, paths: Paths) -> None:
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    pct = (summary.passed / summary.total * 100) if summary.total else 0.0
    rows = "\n".join(
        f"<tr class='{r.status.value.lower()}'><td>{r.test_id}</td><td>{_esc(r.title)}</td>"
        f"<td>{r.status.value}</td><td>{r.duration_ms}</td><td><pre>{_esc(r.error)}</pre></td></tr>"
        for r in summary.results
    )
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Suitest — {_esc(summary.project)}</title>
<style>
 body{{font-family:ui-sans-serif,system-ui,sans-serif;background:#0a0a0a;color:#fafafa;margin:0;padding:2rem}}
 h1{{font-size:1.4rem}} .meta{{color:#a3a3a3;margin-bottom:1rem}}
 table{{border-collapse:collapse;width:100%;font-size:.85rem}}
 th,td{{border:1px solid #262626;padding:.4rem .6rem;text-align:left;vertical-align:top}}
 th{{background:#161616}} pre{{margin:0;white-space:pre-wrap;color:#f87171;font-size:.75rem}}
 tr.passed td:nth-child(3){{color:#4ade80}} tr.failed td:nth-child(3),tr.error td:nth-child(3){{color:#f87171}}
 .pill{{display:inline-block;padding:.2rem .6rem;border-radius:999px;background:#161616;margin-right:.4rem}}
</style></head><body>
<h1>Suitest Report — {_esc(summary.project)} ({summary.mode.value})</h1>
<div class="meta">
 <span class="pill">Base: {_esc(summary.base_url)}</span>
 <span class="pill">Ready: {"yes" if summary.ready else "NO"}</span>
 <span class="pill">Pass: {summary.passed}/{summary.total} ({pct:.0f}%)</span>
 <span class="pill">{summary.duration_ms} ms</span>
</div>
<table><thead><tr><th>ID</th><th>Title</th><th>Status</th><th>ms</th><th>Error</th></tr></thead>
<tbody>{rows}</tbody></table>
</body></html>"""
    (paths.reports_dir / "summary.html").write_text(html, encoding="utf-8")


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def write_all_reports(summary: RunSummary, paths: Paths, date: str) -> None:
    write_raw_report(summary, paths, date)
    write_summary_json(summary, paths)
    write_summary_md(summary, paths)
    write_summary_html(summary, paths)


__all__ = [
    "write_all_reports",
    "write_raw_report",
    "write_summary_html",
    "write_summary_json",
    "write_summary_md",
]
