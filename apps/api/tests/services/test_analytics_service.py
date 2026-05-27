"""AnalyticsService tests — flaky threshold + workspace scoping.

Flaky gate (M1-26): variance > 0.2 AND case appeared in >= 3 of the last 10 runs.
We construct per-case outcome histories that land on either side of the gate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from suitest_api.deps.scope import TenantContext
from suitest_api.services.analytics_service import AnalyticsService
from suitest_db.models.case import TestCase
from suitest_db.models.project import Project
from suitest_db.models.run import Run, RunStep
from suitest_shared.domain.enums import (
    CaseSource,
    Role,
    RunStatus,
    RunTrigger,
    StepOutcome,
    Tier,
)

_NOW = datetime(2026, 5, 28, tzinfo=UTC)


def _ctx(ws: str = "ws_1") -> TenantContext:
    return TenantContext(
        workspace_id=ws, user_id="00000000-0000-0000-0000-000000000001", role=Role.QA
    )


def _project(ws: str) -> Project:
    p = Project(id="proj_1", workspace_id=ws, slug="p", name="P")
    p.created_at = _NOW
    p.updated_at = _NOW
    return p


def _run(run_id: str) -> Run:
    r = Run(
        id=run_id,
        public_id=run_id.upper(),
        project_id="proj_1",
        name=run_id,
        trigger=RunTrigger.MANUAL,
        tier_at_runtime=Tier.ZERO,
        status=RunStatus.PASS,
    )
    r.created_at = _NOW
    r.updated_at = _NOW
    return r


def _step(run_id: str, case_id: str, outcome: StepOutcome) -> RunStep:
    rs = RunStep(
        id=f"{run_id}-{case_id}",
        run_id=run_id,
        case_id=case_id,
        step_order=1,
        outcome=outcome,
    )
    rs.created_at = _NOW
    rs.updated_at = _NOW
    return rs


def _case(case_id: str) -> TestCase:
    c = TestCase(
        id=case_id,
        suite_id="suite_1",
        public_id=case_id.upper(),
        name=case_id,
        source=CaseSource.MANUAL,
    )
    c.created_at = _NOW
    c.updated_at = _NOW
    return c


_P = StepOutcome.PASS
_F = StepOutcome.FAIL

# Per-run, per-case outcomes. 5 runs.
#   case_flaky: [P,P,F,F,F] -> mean 0.4, pvariance 0.24 (> 0.2) -> flagged (n=5)
#   case_stable:[P,P,P,P,F] -> mean 0.8, pvariance 0.16 (< 0.2) -> not flagged
#   case_rare:  appears in only 2 runs [P,F] -> variance 0.25 but n=2 < 3 -> not flagged
_PLAN = {
    "run_1": {"case_flaky": _P, "case_stable": _P, "case_rare": _P},
    "run_2": {"case_flaky": _P, "case_stable": _P, "case_rare": _F},
    "run_3": {"case_flaky": _F, "case_stable": _P},
    "run_4": {"case_flaky": _F, "case_stable": _P},
    "run_5": {"case_flaky": _F, "case_stable": _F},
}


def _build_repos(ws: str = "ws_1") -> tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    run_repo = AsyncMock()
    project_repo = AsyncMock()
    requirement_repo = AsyncMock()
    test_case_repo = AsyncMock()
    defect_repo = AsyncMock()

    project_repo.get_by_id.return_value = _project(ws)
    run_repo.list_by_project.return_value = ([_run(rid) for rid in _PLAN], None)

    steps_by_run = {
        rid: [_step(rid, cid, oc) for cid, oc in cases.items()] for rid, cases in _PLAN.items()
    }

    async def _get_steps(run_id: str) -> list[RunStep]:
        return steps_by_run[run_id]

    run_repo.get_steps.side_effect = _get_steps

    async def _get_case(case_id: str) -> TestCase:
        return _case(case_id)

    test_case_repo.get_by_id.side_effect = _get_case
    return run_repo, project_repo, requirement_repo, test_case_repo, defect_repo


def _service(ws: str = "ws_1") -> AnalyticsService:
    run_repo, project_repo, requirement_repo, test_case_repo, defect_repo = _build_repos(ws)
    return AnalyticsService(
        _ctx(ws), run_repo, project_repo, requirement_repo, test_case_repo, defect_repo
    )


@pytest.mark.asyncio
async def test_analytics_flaky_threshold() -> None:
    svc = _service()
    flaky = await svc.flaky("proj_1")

    assert flaky is not None
    flagged = {f.case_id for f in flaky}
    # variance 0.24 (> 0.2) with n=5 -> flagged
    assert "case_flaky" in flagged
    # variance 0.16 (< 0.2) -> not flagged
    assert "case_stable" not in flagged
    # n=2 (< 3) regardless of variance -> not flagged
    assert "case_rare" not in flagged

    entry = next(f for f in flaky if f.case_id == "case_flaky")
    assert entry.sample_size == 5
    assert entry.public_id == "CASE_FLAKY"


@pytest.mark.asyncio
async def test_analytics_flaky_404_when_cross_workspace() -> None:
    # project resolves to ws_OTHER but the request ctx is ws_1 -> out of scope.
    run_repo, project_repo, requirement_repo, test_case_repo, defect_repo = _build_repos("ws_OTHER")
    svc = AnalyticsService(
        _ctx("ws_1"), run_repo, project_repo, requirement_repo, test_case_repo, defect_repo
    )
    assert await svc.flaky("proj_1") is None


@pytest.mark.asyncio
async def test_analytics_pass_rate_and_coverage() -> None:
    run_repo, project_repo, requirement_repo, test_case_repo, defect_repo = _build_repos("ws_1")
    requirement_repo.list_by_project.return_value = []
    svc = AnalyticsService(
        _ctx("ws_1"), run_repo, project_repo, requirement_repo, test_case_repo, defect_repo
    )

    pr = await svc.pass_rate("proj_1")
    assert pr is not None
    # all 5 runs are RunStatus.PASS in _run()
    assert pr.pass_rate == 1.0
    assert pr.sample_size == 5

    cov = await svc.coverage("proj_1")
    assert cov is not None
    assert cov.coverage_rate == 0.0
