"""Analytics read endpoints (docs/API.md §3.8) — project-scoped, deterministic.

All endpoints resolve the project's workspace scope first (404 on cross-workspace).
The ``period`` query is parsed by :func:`_parse_period` (``^(\\d+)d$`` → days, else
400). Readiness is a deterministic score (no LLM):
``score = 100 - 10*open_critical - 5*open_high - 2*unlinked_requirements`` clamped
to ``[0, 100]``, with a blocker per open CRITICAL defect and per unlinked requirement.
Flaky reuses the Task 4 ``AnalyticsService``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.defects import DefectRepo
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.requirements import RequirementRepo
from suitest_db.repositories.runs import RunRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_db.repositories.test_cases import TestCaseRepo
from suitest_shared.domain.enums import RunStatus, Severity

from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.schemas.analytics import (
    CoverageOut,
    CoverageRequirementRow,
    CoverageSuiteRow,
    FlakyCaseOut,
    HeatmapCell,
    KpisOut,
    PassRatePoint,
    PassRateSeriesOut,
    ReadinessBlocker,
    ReadinessOut,
)
from suitest_api.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/api/v1", tags=["analytics"])

_PERIOD_RE = re.compile(r"^(\d+)d$")
_PASS = RunStatus.PASS
_FAIL = {RunStatus.FAIL, RunStatus.ERROR}


def _parse_period(period: str) -> timedelta:
    """Parse ``<n>d`` → ``timedelta(days=n)``; raise 400 on any other format."""
    match = _PERIOD_RE.match(period)
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid period {period!r}: expected '<n>d' (e.g. 7d, 30d)",
        )
    return timedelta(days=int(match.group(1)))


async def _project_or_404(session: AsyncSession, project_id: str, workspace_id: str) -> None:
    project = await ProjectRepo(session).get_by_id(project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")


@router.get("/analytics/kpis", response_model=KpisOut, response_model_by_alias=True)
async def analytics_kpis(
    project_id: str = Query(alias="projectId"),
    period: str = Query(default="7d"),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> KpisOut:
    """Pass rate, run count, avg duration, and open defect count for the window."""
    await _project_or_404(session, project_id, ctx.workspace_id)
    since = datetime.now(tz=UTC) - _parse_period(period)
    runs = await RunRepo(session).list_since(project_id, since)
    terminal = [r for r in runs if r.status is _PASS or r.status in _FAIL]
    passed = sum(1 for r in terminal if r.status is _PASS)
    durations = [r.duration_ms for r in runs if r.duration_ms is not None]
    defects_open = await DefectRepo(session).count_open(ctx.workspace_id)
    return KpisOut(
        pass_rate=(passed / len(terminal)) if terminal else 0.0,
        run_count=len(runs),
        avg_duration_ms=(sum(durations) / len(durations)) if durations else 0.0,
        defects_open=defects_open,
    )


@router.get("/analytics/pass-rate", response_model=PassRateSeriesOut, response_model_by_alias=True)
async def analytics_pass_rate(
    project_id: str = Query(alias="projectId"),
    period: str = Query(default="30d"),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> PassRateSeriesOut:
    """Daily pass-rate time series (ascending by date) over the window."""
    await _project_or_404(session, project_id, ctx.workspace_id)
    since = datetime.now(tz=UTC) - _parse_period(period)
    runs = await RunRepo(session).list_since(project_id, since)
    by_day: dict[str, tuple[int, int]] = {}  # date -> (passed, terminal)
    total = 0
    for r in runs:
        if r.status is not _PASS and r.status not in _FAIL:
            continue
        total += 1
        day = r.created_at.date().isoformat()
        passed, terminal = by_day.get(day, (0, 0))
        by_day[day] = (passed + (1 if r.status is _PASS else 0), terminal + 1)
    series = [
        PassRatePoint(date=day, pass_rate=(passed / terminal) if terminal else 0.0)
        for day, (passed, terminal) in sorted(by_day.items())
    ]
    return PassRateSeriesOut(series=series, total=total)


@router.get("/analytics/coverage", response_model=CoverageOut, response_model_by_alias=True)
async def analytics_coverage(
    project_id: str = Query(alias="projectId"),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> CoverageOut:
    """Coverage by suite (cases with a requirement link) + by requirement."""
    await _project_or_404(session, project_id, ctx.workspace_id)
    suite_repo = SuiteRepo(session)
    suites = await suite_repo.list_by_project(project_id)
    suite_ids = [s.id for s in suites]
    totals = await suite_repo.case_counts(suite_ids)
    covered = await suite_repo.covered_case_counts(suite_ids)
    by_suite = [
        CoverageSuiteRow(
            suite_id=s.id,
            name=s.name,
            total=totals.get(s.id, 0),
            covered=covered.get(s.id, 0),
            coverage=(covered.get(s.id, 0) / totals[s.id]) if totals.get(s.id) else 0.0,
        )
        for s in suites
    ]

    req_repo = RequirementRepo(session)
    requirements = await req_repo.list_by_project(project_id)
    link_counts = await req_repo.link_counts([r.id for r in requirements])
    by_requirement = [
        CoverageRequirementRow(
            requirement_id=r.public_id,
            total=link_counts.get(r.id, 0),
            covered=1 if link_counts.get(r.id, 0) > 0 else 0,
        )
        for r in requirements
    ]
    return CoverageOut(by_suite=by_suite, by_requirement=by_requirement)


@router.get("/analytics/flaky", response_model=list[FlakyCaseOut], response_model_by_alias=True)
async def analytics_flaky(
    project_id: str = Query(alias="projectId"),
    min_rate: float = Query(default=0.20, alias="minRate"),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[FlakyCaseOut]:
    """Flaky cases above ``minRate`` (reuses the Task 4 AnalyticsService rule)."""
    await _project_or_404(session, project_id, ctx.workspace_id)
    service = AnalyticsService(
        ctx,
        RunRepo(session),
        ProjectRepo(session),
        RequirementRepo(session),
        TestCaseRepo(session),
        DefectRepo(session),
    )
    flaky = await service.flaky(project_id, min_rate=min_rate)
    rows = flaky or []
    return [
        FlakyCaseOut(
            case_id=f.case_id,
            public_id=f.public_id,
            flake_rate=f.flake_rate,
            sample_size=f.sample_size,
        )
        for f in rows
    ]


@router.get("/analytics/heatmap", response_model=list[HeatmapCell])
async def analytics_heatmap(
    project_id: str = Query(alias="projectId"),
    period: str = Query(default="14d"),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[HeatmapCell]:
    """Run-count grid (day x hour) over the window (docs/API.md §3.8)."""
    await _project_or_404(session, project_id, ctx.workspace_id)
    since = datetime.now(tz=UTC) - _parse_period(period)
    cells = await RunRepo(session).heatmap_cells(project_id, since)
    return [HeatmapCell(day=day, hour=hour, count=count) for day, hour, count in cells]


@router.get("/analytics/readiness", response_model=ReadinessOut)
async def analytics_readiness(
    project_id: str = Query(alias="projectId"),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> ReadinessOut:
    """Deterministic release-readiness score + blocker list (no LLM)."""
    await _project_or_404(session, project_id, ctx.workspace_id)
    defect_repo = DefectRepo(session)
    open_critical = await defect_repo.list_open_by_severity(ctx.workspace_id, Severity.CRITICAL)
    open_high = await defect_repo.count_open(ctx.workspace_id, severity=Severity.HIGH)

    req_repo = RequirementRepo(session)
    requirements = await req_repo.list_by_project(project_id)
    link_counts = await req_repo.link_counts([r.id for r in requirements])
    unlinked = [r for r in requirements if link_counts.get(r.id, 0) == 0]

    raw = 100 - (10 * len(open_critical)) - (5 * open_high) - (2 * len(unlinked))
    score = max(0, min(100, raw))

    blockers: list[ReadinessBlocker] = []
    for defect in open_critical:
        blockers.append(
            ReadinessBlocker(
                type="open_critical_defect",
                message=f"Open CRITICAL defect {defect.public_id}: {defect.title}",
                ref=defect.public_id,
            )
        )
    for req in unlinked:
        blockers.append(
            ReadinessBlocker(
                type="unlinked_requirement",
                message=f"Requirement {req.public_id} has no linked test case",
                ref=req.public_id,
            )
        )
    return ReadinessOut(score=score, blockers=blockers)
