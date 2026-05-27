"""AnalyticsService — project-scoped KPIs, coverage, flaky detection, readiness.

Scope: every method first verifies the project belongs to ``ctx.workspace_id``
(via ``ProjectRepo``); cross-workspace project ids return ``None``.

Flaky rule (M1-26)
------------------
Implemented in **Python aggregation** (not a SQL window function). Rationale: the
"last 10 runs in which a case appeared" window is per-case and depends on
run-level ordering joined to ``run_steps``; expressing it as a single portable
SQL window across SQLAlchemy + the mocked-repo test seam was gnarlier than the
straightforward Python pass below. The repo already exposes ``list_by_project``
(ordered newest-first) and ``get_steps(run_id)``, so we aggregate in-process.

Per case: collect the per-run outcome from the most-recent runs (PASS=1,
FAIL=0, ERROR=0; SKIP/PENDING ignored), keep at most the last 10 in which the
case appeared, compute the population variance, and flag flaky when
``variance > 0.2`` AND the case appeared in ``>= 3`` of those runs.
"""

from __future__ import annotations

import statistics
from typing import TYPE_CHECKING

from suitest_core.capabilities import TierFlag
from suitest_db.repositories.defects import DefectRepo
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.requirements import RequirementRepo
from suitest_db.repositories.runs import RunRepo
from suitest_db.repositories.test_cases import TestCaseRepo
from suitest_shared.domain.enums import DefectStatus, RunStatus, Severity, StepOutcome
from suitest_shared.schemas.responses import (
    CoverageOut,
    FlakyCaseOut,
    HeatmapCellOut,
    HeatmapOut,
    KpiOut,
    PassRateOut,
    ReadinessOut,
)

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier

if TYPE_CHECKING:
    from suitest_db.models.run import Run

# Most recent runs considered per flaky window, and gates from M1-26.
FLAKY_WINDOW = 10
FLAKY_MIN_SAMPLES = 3
# A run counts toward pass-rate when it reached a terminal pass/fail state.
_TERMINAL_PASS = RunStatus.PASS
_TERMINAL_FAIL = {RunStatus.FAIL, RunStatus.ERROR}


def _outcome_to_int(outcome: StepOutcome) -> int | None:
    """PASS -> 1, FAIL/ERROR -> 0, SKIP/PENDING -> None (ignored in variance)."""
    if outcome is StepOutcome.PASS:
        return 1
    if outcome in (StepOutcome.FAIL, StepOutcome.ERROR):
        return 0
    return None


class AnalyticsService:
    def __init__(
        self,
        ctx: TenantContext,
        run_repo: RunRepo,
        project_repo: ProjectRepo,
        requirement_repo: RequirementRepo,
        test_case_repo: TestCaseRepo,
        defect_repo: DefectRepo,
    ) -> None:
        self._ctx = ctx
        self._run_repo = run_repo
        self._project_repo = project_repo
        self._requirement_repo = requirement_repo
        self._test_case_repo = test_case_repo
        self._defect_repo = defect_repo

    async def _project_in_scope(self, project_id: str) -> bool:
        project = await self._project_repo.get_by_id(project_id)
        return project is not None and project.workspace_id == self._ctx.workspace_id

    async def _recent_runs(self, project_id: str) -> list[Run]:
        rows, _ = await self._run_repo.list_by_project(project_id, limit=FLAKY_WINDOW)
        return list(rows)

    @require_tier(TierFlag.ANY)
    async def pass_rate(self, project_id: str, period: str = "30d") -> PassRateOut | None:
        if not await self._project_in_scope(project_id):
            return None
        runs = await self._recent_runs(project_id)
        terminal = [r for r in runs if r.status is _TERMINAL_PASS or r.status in _TERMINAL_FAIL]
        passed = sum(1 for r in terminal if r.status is _TERMINAL_PASS)
        rate = passed / len(terminal) if terminal else 0.0
        return PassRateOut(
            project_id=project_id, period=period, pass_rate=rate, sample_size=len(terminal)
        )

    @require_tier(TierFlag.ANY)
    async def coverage(self, project_id: str) -> CoverageOut | None:
        if not await self._project_in_scope(project_id):
            return None
        requirements = await self._requirement_repo.list_by_project(project_id)
        total = len(requirements)
        covered = 0
        for req in requirements:
            links = await self._requirement_repo.with_links(req.id)
            if links:
                covered += 1
        rate = covered / total if total else 0.0
        return CoverageOut(
            project_id=project_id,
            total_requirements=total,
            covered_requirements=covered,
            coverage_rate=rate,
        )

    @require_tier(TierFlag.ANY)
    async def kpis(self, project_id: str, period: str = "30d") -> KpiOut | None:
        if not await self._project_in_scope(project_id):
            return None
        pr = await self.pass_rate(project_id, period)
        defects, _ = await self._defect_repo.list_by_workspace(
            self._ctx.workspace_id, status=DefectStatus.OPEN, limit=FLAKY_WINDOW
        )
        runs = await self._recent_runs(project_id)
        return KpiOut(
            project_id=project_id,
            period=period,
            total_runs=len(runs),
            pass_rate=pr.pass_rate if pr else 0.0,
            total_cases=pr.sample_size if pr else 0,
            open_defects=len(defects),
        )

    @require_tier(TierFlag.ANY)
    async def flaky(self, project_id: str, min_rate: float = 0.2) -> list[FlakyCaseOut] | None:
        if not await self._project_in_scope(project_id):
            return None
        # Python aggregation (see module docstring): per case, the chronological
        # list of binary outcomes across the recent runs in which it appeared.
        outcomes_by_case = await self._binary_outcomes_by_case(project_id)
        # ``min_rate`` is the variance gate (default 0.2 per M1-26); a higher value
        # narrows what counts as flaky.
        flaky: list[FlakyCaseOut] = []
        for case_id, values in outcomes_by_case.items():
            window = values[:FLAKY_WINDOW]
            sample_size = len(window)
            if sample_size < FLAKY_MIN_SAMPLES:
                continue
            if statistics.pvariance(window) <= min_rate:
                continue
            flake_rate = 1.0 - (sum(window) / sample_size)  # fraction of non-passes
            case = await self._test_case_repo.get_by_id(case_id)
            public_id = case.public_id if case is not None else case_id
            flaky.append(
                FlakyCaseOut(
                    case_id=case_id,
                    public_id=public_id,
                    flake_rate=flake_rate,
                    sample_size=sample_size,
                )
            )
        return flaky

    async def _binary_outcomes_by_case(self, project_id: str) -> dict[str, list[int]]:
        """Map case_id -> chronological PASS=1/FAIL=ERROR=0 list over recent runs."""
        runs = await self._recent_runs(project_id)
        outcomes_by_case: dict[str, list[int]] = {}
        for run in runs:
            steps = await self._run_repo.get_steps(run.id)
            for step in steps:
                value = _outcome_to_int(step.outcome)
                if value is None:
                    continue
                outcomes_by_case.setdefault(step.case_id, []).append(value)
        return outcomes_by_case

    @require_tier(TierFlag.ANY)
    async def heatmap(self, project_id: str, period: str = "30d") -> HeatmapOut | None:
        if not await self._project_in_scope(project_id):
            return None
        runs = await self._recent_runs(project_id)
        outcomes_by_case: dict[str, list[StepOutcome]] = {}
        for run in runs:
            steps = await self._run_repo.get_steps(run.id)
            for step in steps:
                outcomes_by_case.setdefault(step.case_id, []).append(step.outcome)
        cells: list[HeatmapCellOut] = []
        for case_id, outcomes in outcomes_by_case.items():
            case = await self._test_case_repo.get_by_id(case_id)
            public_id = case.public_id if case is not None else case_id
            cells.append(HeatmapCellOut(case_id=case_id, public_id=public_id, outcomes=outcomes))
        return HeatmapOut(project_id=project_id, period=period, cells=cells)

    @require_tier(TierFlag.ANY)
    async def readiness(self, project_id: str) -> ReadinessOut | None:
        if not await self._project_in_scope(project_id):
            return None
        pr = await self.pass_rate(project_id)
        cov = await self.coverage(project_id)
        crit_defects, _ = await self._defect_repo.list_by_workspace(
            self._ctx.workspace_id,
            status=DefectStatus.OPEN,
            severity=Severity.CRITICAL,
            limit=FLAKY_WINDOW,
        )
        pass_rate_v = pr.pass_rate if pr else 0.0
        coverage_v = cov.coverage_rate if cov else 0.0
        open_critical = len(crit_defects)
        # Simple weighted readiness score for M1a; real model lands per API.md.
        score = round((pass_rate_v * 0.6 + coverage_v * 0.4), 4)
        ready = score >= 0.8 and open_critical == 0
        return ReadinessOut(
            project_id=project_id,
            score=score,
            pass_rate=pass_rate_v,
            coverage_rate=coverage_v,
            open_critical_defects=open_critical,
            ready=ready,
        )
