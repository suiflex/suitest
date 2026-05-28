"""Task 7i — analytics read endpoint tests (docs/API.md §3.8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from suitest_db.models.case import TestCase
from suitest_db.models.defect import Defect
from suitest_db.models.project import Project, Suite
from suitest_db.models.requirement import Requirement, RequirementLink
from suitest_db.models.run import Run, RunStep
from suitest_shared.domain.enums import (
    CaseSource,
    DefectStatus,
    RunStatus,
    RunTrigger,
    Severity,
    StepOutcome,
    Tier,
)

if TYPE_CHECKING:
    from api_harness import ApiDb


async def _project(api_db: ApiDb, ws_id: str, *, slug: str = "an-proj") -> Project:
    proj = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([proj])
    return proj


def _run(project_id: str, public_id: str, *, status: RunStatus, **kw: object) -> Run:
    return Run(
        public_id=public_id,
        project_id=project_id,
        name="run",
        trigger=RunTrigger.MANUAL,
        tier_at_runtime=Tier.ZERO,
        status=status,
        **kw,
    )


@pytest.mark.asyncio
async def test_kpis_seven_day_window(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="an-kpi@example.com")
    ws = await api_db.member_workspace(user, slug="an-kpi-ws")
    proj = await _project(api_db, ws.id)
    await api_db.add_all(
        [
            _run(proj.id, "AN-K1", status=RunStatus.PASS, duration_ms=100),
            _run(proj.id, "AN-K2", status=RunStatus.PASS, duration_ms=300),
            _run(proj.id, "AN-K3", status=RunStatus.FAIL, duration_ms=200),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/analytics/kpis?projectId={proj.id}&period=7d",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["runCount"] == 3
    assert data["passRate"] == pytest.approx(2 / 3)
    assert data["avgDurationMs"] == pytest.approx(200.0)
    assert data["defectsOpen"] == 0


@pytest.mark.asyncio
async def test_pass_rate_time_series_ordered_ascending(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="an-pr@example.com")
    ws = await api_db.member_workspace(user, slug="an-pr-ws")
    proj = await _project(api_db, ws.id)
    now = datetime.now(tz=UTC)
    r1 = _run(proj.id, "AN-PR1", status=RunStatus.PASS)
    r2 = _run(proj.id, "AN-PR2", status=RunStatus.FAIL)
    r1.created_at = now - timedelta(days=2)
    r2.created_at = now - timedelta(days=1)
    await api_db.add_all([r1, r2])
    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/analytics/pass-rate?projectId={proj.id}&period=30d",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    data = resp.json()
    dates = [p["date"] for p in data["series"]]
    assert dates == sorted(dates)
    assert data["total"] == 2


@pytest.mark.asyncio
async def test_coverage_by_suite_correct(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="an-cov-s@example.com")
    ws = await api_db.member_workspace(user, slug="an-cov-s-ws")
    proj = await _project(api_db, ws.id)
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    cases = [
        TestCase(suite_id=suite.id, public_id=f"TC-AC{i}", name=f"c{i}", source=CaseSource.MANUAL)
        for i in range(3)
    ]
    await api_db.add_all(cases)
    req = Requirement(project_id=proj.id, public_id="REQ-AC1", title="r")
    await api_db.add_all([req])
    await api_db.add_all([RequirementLink(requirement_id=req.id, case_id=cases[0].id)])

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/analytics/coverage?projectId={proj.id}", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    by_suite = resp.json()["bySuite"]
    row = next(s for s in by_suite if s["suiteId"] == suite.id)
    assert row["total"] == 3
    assert row["covered"] == 1
    assert row["coverage"] == pytest.approx(1 / 3)


@pytest.mark.asyncio
async def test_coverage_by_requirement_correct(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="an-cov-r@example.com")
    ws = await api_db.member_workspace(user, slug="an-cov-r-ws")
    proj = await _project(api_db, ws.id)
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(suite_id=suite.id, public_id="TC-AR1", name="c", source=CaseSource.MANUAL)
    await api_db.add_all([case])
    linked = Requirement(project_id=proj.id, public_id="REQ-AR1", title="linked")
    unlinked = Requirement(project_id=proj.id, public_id="REQ-AR2", title="unlinked")
    await api_db.add_all([linked, unlinked])
    await api_db.add_all([RequirementLink(requirement_id=linked.id, case_id=case.id)])

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/analytics/coverage?projectId={proj.id}", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    by_req = {r["requirementId"]: r for r in resp.json()["byRequirement"]}
    assert by_req["REQ-AR1"]["covered"] == 1
    assert by_req["REQ-AR2"]["covered"] == 0


async def _flaky_setup(api_db: ApiDb, ws_id: str) -> tuple[str, str]:
    """Seed a project + one case appearing in 5 runs with a 3/2 pass/fail split."""
    proj = await _project(api_db, ws_id, slug="an-flaky-proj")
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(suite_id=suite.id, public_id="TC-FLAKE", name="flaky", source=CaseSource.MANUAL)
    await api_db.add_all([case])
    outcomes = [
        StepOutcome.PASS,
        StepOutcome.FAIL,
        StepOutcome.PASS,
        StepOutcome.FAIL,
        StepOutcome.PASS,
    ]
    for i, outcome in enumerate(outcomes):
        run = _run(proj.id, f"AN-FL{i}", status=RunStatus.PASS)
        await api_db.add_all([run])
        await api_db.add_all(
            [RunStep(run_id=run.id, case_id=case.id, step_order=1, outcome=outcome)]
        )
    return proj.id, case.id


@pytest.mark.asyncio
async def test_flaky_endpoint_threshold_default_20pct(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="an-flaky@example.com")
    ws = await api_db.member_workspace(user, slug="an-flaky-ws")
    project_id, _ = await _flaky_setup(api_db, ws.id)
    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/analytics/flaky?projectId={project_id}", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    rows = resp.json()
    assert any(r["publicId"] == "TC-FLAKE" for r in rows)


@pytest.mark.asyncio
async def test_flaky_endpoint_min_rate_query_param(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="an-flaky2@example.com")
    ws = await api_db.member_workspace(user, slug="an-flaky2-ws")
    project_id, _ = await _flaky_setup(api_db, ws.id)
    # A very high min_rate (variance gate) should exclude the moderately flaky case.
    async with api_db.client(user) as c:
        strict = await c.get(
            f"/api/v1/analytics/flaky?projectId={project_id}&minRate=0.99",
            headers={"X-Workspace-Id": ws.id},
        )
        loose = await c.get(
            f"/api/v1/analytics/flaky?projectId={project_id}&minRate=0.10",
            headers={"X-Workspace-Id": ws.id},
        )
    assert strict.status_code == 200
    assert loose.status_code == 200
    assert len(loose.json()) >= len(strict.json())


@pytest.mark.asyncio
async def test_heatmap_day_hour_grid(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="an-heat@example.com")
    ws = await api_db.member_workspace(user, slug="an-heat-ws")
    proj = await _project(api_db, ws.id)
    base = datetime(2026, 5, 20, 9, 30, tzinfo=UTC)
    r1 = _run(proj.id, "AN-H1", status=RunStatus.PASS)
    r2 = _run(proj.id, "AN-H2", status=RunStatus.PASS)
    r1.created_at = base
    r2.created_at = base + timedelta(minutes=10)  # same day + hour → grouped
    await api_db.add_all([r1, r2])
    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/analytics/heatmap?projectId={proj.id}&period=3650d",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    cells = resp.json()
    cell = next(c for c in cells if c["hour"] == 9)
    assert cell["count"] == 2


@pytest.mark.asyncio
async def test_readiness_score_caps_at_zero_when_many_blockers(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="an-rdy0@example.com")
    ws = await api_db.member_workspace(user, slug="an-rdy0-ws")
    proj = await _project(api_db, ws.id)
    # 11 open CRITICAL defects → -110 → clamped to 0.
    await api_db.add_all(
        [
            Defect(
                public_id=f"SUIT-RC{i}",
                workspace_id=ws.id,
                title=f"crit {i}",
                severity=Severity.CRITICAL,
                status=DefectStatus.OPEN,
                created_by="seed",
            )
            for i in range(11)
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/analytics/readiness?projectId={proj.id}", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    assert resp.json()["score"] == 0


@pytest.mark.asyncio
async def test_readiness_blockers_list(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="an-rdy@example.com")
    ws = await api_db.member_workspace(user, slug="an-rdy-ws")
    proj = await _project(api_db, ws.id)
    await api_db.add_all(
        [
            Defect(
                public_id="SUIT-RDY1",
                workspace_id=ws.id,
                title="crit",
                severity=Severity.CRITICAL,
                status=DefectStatus.OPEN,
                created_by="seed",
            )
        ]
    )
    await api_db.add_all([Requirement(project_id=proj.id, public_id="REQ-RDY1", title="orphan")])
    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/analytics/readiness?projectId={proj.id}", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    data = resp.json()
    # 100 - 10*1 (critical) - 2*1 (unlinked req) = 88
    assert data["score"] == 88
    types = {b["type"] for b in data["blockers"]}
    assert types == {"open_critical_defect", "unlinked_requirement"}


@pytest.mark.asyncio
async def test_analytics_invalid_period_400(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="an-bad@example.com")
    ws = await api_db.member_workspace(user, slug="an-bad-ws")
    proj = await _project(api_db, ws.id)
    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/analytics/kpis?projectId={proj.id}&period=7days",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_analytics_kpis_404_cross_workspace(api_db: ApiDb) -> None:
    """Member of workspace A passing a workspace-B projectId gets 404, not data."""
    user = await api_db.seed_user(email="an-xws-kpi@example.com")
    ws_a = await api_db.member_workspace(user, slug="an-xws-a")
    # Foreign workspace B: user is NOT a member. Seed a project that lives in B.
    ws_b = await api_db.seed_workspace(slug="an-xws-b", name="B")
    foreign_proj = await _project(api_db, ws_b.id, slug="an-xws-foreign")
    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/analytics/kpis?projectId={foreign_proj.id}",
            headers={"X-Workspace-Id": ws_a.id},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_analytics_readiness_404_cross_workspace(api_db: ApiDb) -> None:
    """Readiness must also refuse a foreign-workspace projectId with 404."""
    user = await api_db.seed_user(email="an-xws-rdy@example.com")
    ws_a = await api_db.member_workspace(user, slug="an-xws-rdy-a")
    ws_b = await api_db.seed_workspace(slug="an-xws-rdy-b", name="B")
    foreign_proj = await _project(api_db, ws_b.id, slug="an-xws-rdy-foreign")
    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/analytics/readiness?projectId={foreign_proj.id}",
            headers={"X-Workspace-Id": ws_a.id},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_analytics_coverage_404_cross_workspace(api_db: ApiDb) -> None:
    """Coverage must also refuse a foreign-workspace projectId with 404."""
    user = await api_db.seed_user(email="an-xws-cov@example.com")
    ws_a = await api_db.member_workspace(user, slug="an-xws-cov-a")
    ws_b = await api_db.seed_workspace(slug="an-xws-cov-b", name="B")
    foreign_proj = await _project(api_db, ws_b.id, slug="an-xws-cov-foreign")
    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/analytics/coverage?projectId={foreign_proj.id}",
            headers={"X-Workspace-Id": ws_a.id},
        )
    assert resp.status_code == 404
