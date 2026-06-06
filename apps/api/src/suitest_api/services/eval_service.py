"""Eval harness (M4-8) — scores generator/diagnosis quality against golden fixtures.

Runs the three fixture suites shipped under ``eval/fixtures`` (M4-8a) through
DETERMINISTIC scorers so the harness is green at ZERO tier (DoD: eval must pass
in ZERO before any LLM enrichment):

* ``prds`` — count derivable user-story cases ≥ ``min_cases``.
* ``openapi`` — parse the spec, count operations ≥ ``min_operations``.
* ``failed_runs`` — the rule-based :class:`DefectCategorizer` bucket must equal
  the golden ``expected_category``.

Each suite has an ``index.json`` carrying the golden expectations. The harness is
pure + synchronous (fixtures are tiny); the router persists an ``EvalRun`` row.
LLM-graded eval (semantic scoring via a real provider) layers on top in v1.x.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from suitest_api.services.defect_auto_filer import DefectCategorizer

SUITES = ("prds", "openapi", "failed_runs")


@dataclass(frozen=True)
class FixtureResult:
    """One fixture's pass/fail + a short reason for the report."""

    suite: str
    fixture: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class EvalResult:
    """Aggregate eval outcome across all run suites."""

    suite_name: str
    fixtures_count: int
    passed: int
    failed: int
    results: list[FixtureResult]


def run_eval(fixtures_dir: Path, *, suite_name: str = "default") -> EvalResult:
    """Score every fixture under ``fixtures_dir`` and aggregate pass/fail."""
    results: list[FixtureResult] = []
    results.extend(_score_prds(fixtures_dir / "prds"))
    results.extend(_score_openapi(fixtures_dir / "openapi"))
    results.extend(_score_failed_runs(fixtures_dir / "failed_runs"))
    passed = sum(1 for r in results if r.passed)
    return EvalResult(
        suite_name=suite_name,
        fixtures_count=len(results),
        passed=passed,
        failed=len(results) - passed,
        results=results,
    )


def _as_int(value: object, default: int) -> int:
    return value if isinstance(value, int) else default


def _load_index(suite_dir: Path) -> dict[str, dict[str, object]]:
    index = suite_dir / "index.json"
    if not index.is_file():
        return {}
    parsed = json.loads(index.read_text())
    return parsed if isinstance(parsed, dict) else {}


def _score_prds(suite_dir: Path) -> list[FixtureResult]:
    out: list[FixtureResult] = []
    for name, meta in _load_index(suite_dir).items():
        text = (suite_dir / name).read_text()
        stories = sum(1 for line in text.splitlines() if line.strip().lower().startswith("- as a"))
        min_cases = _as_int(meta.get("min_cases", 1), 1)
        ok = stories >= min_cases
        out.append(FixtureResult("prds", name, ok, f"{stories} stories (min {min_cases})"))
    return out


def _score_openapi(suite_dir: Path) -> list[FixtureResult]:
    out: list[FixtureResult] = []
    methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    for name, meta in _load_index(suite_dir).items():
        spec = json.loads((suite_dir / name).read_text())
        paths = spec.get("paths", {}) if isinstance(spec, dict) else {}
        ops = sum(
            1
            for item in paths.values()
            if isinstance(item, dict)
            for verb in item
            if verb.lower() in methods
        )
        min_ops = _as_int(meta.get("min_operations", 1), 1)
        ok = ops >= min_ops
        out.append(FixtureResult("openapi", name, ok, f"{ops} operations (min {min_ops})"))
    return out


def _score_failed_runs(suite_dir: Path) -> list[FixtureResult]:
    categorizer = DefectCategorizer()
    out: list[FixtureResult] = []
    for name, meta in _load_index(suite_dir).items():
        record = json.loads((suite_dir / name).read_text())
        log = str(record.get("step_log", ""))
        expected = str(meta.get("expected_category", "")) if isinstance(meta, dict) else ""
        kind = categorizer.categorize(stderr=log, stdout="", assertion_message=None)
        ok = kind.value == expected
        out.append(FixtureResult("failed_runs", name, ok, f"got {kind.value}, expected {expected}"))
    return out
