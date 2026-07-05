"""suitest ci — run test di CI, publish PR comment, exit code utk merge gate.

Dipanggil: ``python -m suitest_lifecycle.ci [--config ...] [--dry-run]``
atau via ``npx @suiflex/suitest-mcp ci``.

Exit codes (merge gate): 0 = semua pass · 1 = ada test gagal · 2 = infra error.
"""

from __future__ import annotations

import argparse
import sys

from suitest_lifecycle.ci_report import render_pr_comment
from suitest_lifecycle.publishers import make_publisher

_PASS_STATES = ("PASSED", "PASS")


def exit_code_for(*, failed: int, infra_error: bool) -> int:
    if infra_error:
        return 2
    return 1 if failed else 0


def build_comment_from_run(summary: dict, cases: list[dict], *, dashboard_url: str) -> str:
    return render_pr_comment(
        cases=cases,
        passed=int(summary.get("passed_steps", 0)),
        failed=int(summary.get("failed_steps", 0)),
        duration_ms=summary.get("duration_ms"),
        dashboard_url=dashboard_url,
    )


def _summary_view(data: dict) -> dict:
    """Normalize the run_tests envelope's ``data`` into the flat shape the
    renderer contract wants (passed_steps/failed_steps/duration_ms).

    Deviation from plan: the actual ``run_tests`` envelope stores the run under
    ``data`` directly as ``summary_to_json`` (``totals``/``durationMs``), NOT
    ``data["run"]`` with ``*_steps`` keys as the plan draft assumed.
    """
    totals = data.get("totals") or {}
    return {
        "total_steps": int(totals.get("total", 0)),
        "passed_steps": int(totals.get("passed", 0)),
        "failed_steps": int(totals.get("failed", 0)) + int(totals.get("errored", 0)),
        "duration_ms": data.get("durationMs"),
    }


def _collect_cases(data: dict, config_path: str) -> list[dict]:
    """One row per case (pass AND fail) from the last run's results, enriched
    with a failure excerpt (plan #4) for the failing ones.

    The per-case list comes from the run envelope's ``results`` (authoritative
    pass/fail per test); failure excerpts come from ``load_failed_cases`` keyed
    by title. Evidence links degrade to empty in CI-pure mode (no server URL).
    """
    excerpts = _failure_excerpts(config_path)
    cases: list[dict] = []
    for r in data.get("results") or []:
        if not isinstance(r, dict):
            continue
        title = str(r.get("title") or r.get("testId") or "untitled")
        status = "PASS" if str(r.get("status", "")).upper() in _PASS_STATES else "FAIL"
        row: dict = {"title": title, "status": status, "evidence_url": ""}
        if status == "FAIL" and title in excerpts:
            row["failure_excerpt"] = excerpts[title]
        cases.append(row)
    return cases


def _failure_excerpts(config_path: str) -> dict[str, str]:
    """title -> budgeted failure markdown, from the last run's output dir."""
    try:
        from suitest_lifecycle.config import load_config
        from suitest_lifecycle.failure_context import build_failure_markdown, load_failed_cases

        cfg = load_config(config_path)
        return {
            c.title: build_failure_markdown([c], budget_bytes=1500)
            for c in load_failed_cases(cfg.output_dir)
        }
    except Exception:
        return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="suitest-ci")
    parser.add_argument("--config", default="suitest.config.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="print markdown, jangan publish (debug lokal)")
    args = parser.parse_args(argv)

    # 1. RUN — jalur yang sama dgn MCP tool run_tests
    from suitest_lifecycle.tools import run_tests

    envelope = run_tests(args.config)
    if not isinstance(envelope, dict):
        return 2
    data = envelope.get("data") or {}
    # infra error = gagal sebelum test jalan (no totals/results produced)
    infra_error = not envelope.get("success") and not data.get("totals")

    view = _summary_view(data)
    cases = _collect_cases(data, args.config)

    # 2. RENDER + PUBLISH
    md = build_comment_from_run(view, cases, dashboard_url=str(data.get("dashboard_url", "")))
    if args.dry_run:
        print(md)
    else:
        publisher = make_publisher()
        if publisher is not None:
            publisher.publish(md)
        else:
            print(md)  # forge tak dikenal / no token: print, jangan gagal

    return exit_code_for(failed=view["failed_steps"], infra_error=infra_error)


if __name__ == "__main__":
    sys.exit(main())
