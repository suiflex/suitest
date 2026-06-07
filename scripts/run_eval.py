"""Run the deterministic eval suite over the bundled golden fixtures (M5-2).

Used by the weekly CI workflow (``.github/workflows/m5-eval-weekly.yml``) as a
score-regression gate. Pure ZERO-tier: no DB, no Redis, no LLM — it calls
:func:`suitest_api.services.eval_service.run_eval` directly so it runs on
contributor laptops and CI without booting any services.

Exit codes:

* ``0`` — every fixture passed (and, if ``--baseline`` is given, the score did
  not regress below the baseline).
* ``1`` — one or more fixtures failed, or the score regressed vs. the baseline.

Usage::

    uv run python scripts/run_eval.py
    uv run python scripts/run_eval.py --json /tmp/eval.json
    uv run python scripts/run_eval.py --baseline eval/baseline.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from suitest_api.services.eval_service import run_eval

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_FIXTURES = _REPO_ROOT / "eval" / "fixtures"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic eval suite (M5-2).")
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=_DEFAULT_FIXTURES,
        help="golden fixtures dir (default: eval/fixtures)",
    )
    parser.add_argument("--json", type=Path, default=None, help="write the full report JSON here")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="baseline report JSON; fail if score_pct regresses below it",
    )
    parser.add_argument("--suite-name", default="weekly-ci")
    args = parser.parse_args(argv)

    fixtures_dir: Path = args.fixtures
    if not fixtures_dir.is_dir():
        print(f"eval fixtures dir not found: {fixtures_dir}", file=sys.stderr)
        return 1

    result = run_eval(fixtures_dir, suite_name=args.suite_name)
    score_pct = (
        round(100.0 * result.passed / result.fixtures_count, 1) if result.fixtures_count else 0.0
    )
    report = {
        "suite_name": result.suite_name,
        "fixtures_count": result.fixtures_count,
        "passed": result.passed,
        "failed": result.failed,
        "score_pct": score_pct,
        "results": [
            {"suite": r.suite, "fixture": r.fixture, "passed": r.passed, "detail": r.detail}
            for r in result.results
        ],
    }
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.json is not None:
        args.json.write_text(rendered, encoding="utf-8")

    if result.failed > 0:
        print(f"\nFAIL: {result.failed} fixture(s) failed.", file=sys.stderr)
        return 1

    if args.baseline is not None and args.baseline.is_file():
        baseline = json.loads(args.baseline.read_text())
        baseline_score = float(baseline.get("score_pct", 0.0))
        if score_pct < baseline_score:
            print(
                f"\nFAIL: score regression {score_pct}% < baseline {baseline_score}%.",
                file=sys.stderr,
            )
            return 1

    print(f"\nOK: {result.passed}/{result.fixtures_count} passed ({score_pct}%).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
