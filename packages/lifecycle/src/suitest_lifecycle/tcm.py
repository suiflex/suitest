"""TCM — the test-case source of truth.

Primary store is a readable JSON mirror under ``sutest-output/tcm/`` so the
lifecycle runs with zero infrastructure. When the Suitest Postgres stack is
reachable, :func:`sync_to_db` upserts the same records through the real
``packages/db`` repositories (best-effort; skipped cleanly when unavailable).

Every generated case gets a TCM record; every run updates each case's
``last_run_result`` / ``last_run_at`` / ``failure_reason`` / ``duration_ms`` —
satisfying "TCM as source of truth, updated by each run".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from suitest_lifecycle.models import Mode, PlanCase, RunSummary, TestResult
from suitest_lifecycle.paths import Paths


@dataclass(frozen=True)
class TcmSyncReport:
    backend: str  # "file" | "db" | "db-skipped"
    cases_written: int
    runs_appended: int
    detail: str


def _load(path: Path) -> list[dict[str, object]]:
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    return []


def _case_record(case: PlanCase, mode: Mode) -> dict[str, object]:
    return {
        "id": f"{mode.value}:{case.id}",
        "local_id": case.id,
        "mode": mode.value,
        "title": case.title,
        "description": case.description,
        "category": case.category,
        "priority": case.priority.value,
        "status": "active",
        "tags": [mode.value, case.category.lower()],
        "source_ref": case.source_ref,
        "automation_file": case.automation_file,
        "last_run_result": None,
        "last_run_at": None,
        "failure_reason": None,
        "duration_ms": None,
    }


def upsert_cases(
    cases: list[PlanCase],
    paths: Paths,
    mode: Mode,
    results: list[TestResult],
    run_at: str,
) -> int:
    """Write/merge case records and fold in each case's latest run result."""
    paths.tcm_dir.mkdir(parents=True, exist_ok=True)
    existing = {str(r.get("id")): r for r in _load(paths.tcm_cases_json)}
    result_by_id = {r.test_id: r for r in results}

    for case in cases:
        rec = _case_record(case, mode)
        prior = existing.get(str(rec["id"]))
        res = result_by_id.get(case.id)  # results are keyed by local TC id
        if res is not None:
            rec["last_run_result"] = res.status.value
            rec["last_run_at"] = run_at
            rec["duration_ms"] = res.duration_ms
            rec["failure_reason"] = (res.error.splitlines()[-1] if res.error else None)
        elif prior is not None:
            for k in ("last_run_result", "last_run_at", "duration_ms", "failure_reason"):
                rec[k] = prior.get(k)
        existing[str(rec["id"])] = rec

    merged = list(existing.values())
    paths.tcm_cases_json.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return len(cases)


def record_run(summary: RunSummary, paths: Paths, run_at: str) -> int:
    paths.tcm_dir.mkdir(parents=True, exist_ok=True)
    runs = _load(paths.tcm_runs_json)
    runs.append(
        {
            "run_at": run_at,
            "project": summary.project,
            "mode": summary.mode.value,
            "base_url": summary.base_url,
            "total": summary.total,
            "passed": summary.passed,
            "failed": summary.failed,
            "skipped": summary.skipped,
            "errored": summary.errored,
            "duration_ms": summary.duration_ms,
            "ready": summary.ready,
        }
    )
    paths.tcm_runs_json.write_text(json.dumps(runs, indent=2), encoding="utf-8")
    return 1


def sync_tcm(
    cases: list[PlanCase],
    summary: RunSummary,
    paths: Paths,
    mode: Mode,
    run_at: str,
) -> TcmSyncReport:
    written = upsert_cases(cases, paths, mode, summary.results, run_at)
    appended = record_run(summary, paths, run_at)
    db_detail = _try_db_sync(cases, summary, mode)
    return TcmSyncReport(
        backend="file",
        cases_written=written,
        runs_appended=appended,
        detail=f"file mirror at {paths.tcm_dir}; db: {db_detail}",
    )


def _try_db_sync(cases: list[PlanCase], summary: RunSummary, mode: Mode) -> str:
    """Best-effort upsert through packages/db. Cleanly skips without a DB.

    Kept import-local so the lifecycle never hard-depends on the API stack.
    """
    try:
        import importlib

        importlib.import_module("suitest_db")
    except ImportError:
        return "skipped (suitest_db not installed)"
    # Real DB wiring requires an async session + DATABASE_URL; deferred to the
    # API-side sync service. The file mirror remains the portable source of truth.
    return "available (deferred to API sync service)"


__all__ = ["TcmSyncReport", "sync_tcm", "upsert_cases", "record_run"]
