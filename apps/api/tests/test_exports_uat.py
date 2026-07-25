"""POST /api/v1/projects/{project_id}/exports/uat — UAT PDF export endpoint tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.project import Project, Suite
from suitest_db.models.run import Run, RunStep
from suitest_shared.domain.enums import CaseSource, RunStatus, RunTrigger, StepOutcome, Tier

if TYPE_CHECKING:
    from api_harness import ApiDb


async def _seed_case(
    api_db: ApiDb,
    ws_id: str,
    project_id: str,
    *,
    public_id: str = "TC-UAT1",
) -> tuple[Suite, TestCase]:
    suite = Suite(project_id=project_id, name="UAT Suite", order=0)
    await api_db.add_all([suite])
    case = TestCase(
        suite_id=suite.id,
        workspace_id=ws_id,
        public_id=public_id,
        name="Login smoke",
        source=CaseSource.MANUAL,
    )
    await api_db.add_all([case])
    # add step after case is committed so case.id is populated
    step = TestStep(case_id=case.id, order=0, action="Open login page", expected="Login form visible")
    await api_db.add_all([step])
    return suite, case


@pytest.mark.asyncio
async def test_uat_export_200_returns_pdf(api_db: ApiDb) -> None:
    """Happy path: one case (no run → NOT RUN status) → 200 + PDF bytes."""
    user = await api_db.seed_user(email="uat-export@example.com")
    ws = await api_db.member_workspace(user, slug="uat-export-ws")
    proj = Project(workspace_id=ws.id, slug="uat-proj", name="UAT Project")
    await api_db.add_all([proj])
    _, case = await _seed_case(api_db, ws.id, proj.id)

    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/projects/{proj.id}/exports/uat",
            json={"case_ids": [case.id], "title": "UAT Smoke", "locale": "id"},
            headers={"X-Workspace-Id": ws.id},
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:5] == b"%PDF-"


@pytest.mark.asyncio
async def test_uat_export_200_with_run(api_db: ApiDb) -> None:
    """Case with a completed PASS run → still 200 + PDF."""
    user = await api_db.seed_user(email="uat-export-run@example.com")
    ws = await api_db.member_workspace(user, slug="uat-export-run-ws")
    proj = Project(workspace_id=ws.id, slug="uat-proj-run", name="UAT Run Project")
    await api_db.add_all([proj])
    _, case = await _seed_case(api_db, ws.id, proj.id, public_id="TC-UAT2")

    run = Run(
        public_id="RUN-UAT1",
        project_id=proj.id,
        name="smoke",
        trigger=RunTrigger.MANUAL,
        tier_at_runtime=Tier.ZERO,
        status=RunStatus.PASS,
    )
    await api_db.add_all([run])
    await api_db.add_all([RunStep(run_id=run.id, case_id=case.id, step_order=0, outcome=StepOutcome.PASS)])
    # wire last_run_id so service picks it up
    async with api_db.maker() as session:
        from sqlalchemy import update
        from suitest_db.models.case import TestCase as TC
        await session.execute(update(TC).where(TC.id == case.id).values(last_run_id=run.id))
        await session.commit()

    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/projects/{proj.id}/exports/uat",
            json={"case_ids": [case.id], "title": "UAT Smoke Run", "locale": "en"},
            headers={"X-Workspace-Id": ws.id},
        )

    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"


@pytest.mark.asyncio
async def test_uat_export_404_unknown_case(api_db: ApiDb) -> None:
    """A case_id not in the DB → 404."""
    user = await api_db.seed_user(email="uat-404@example.com")
    ws = await api_db.member_workspace(user, slug="uat-404-ws")
    proj = Project(workspace_id=ws.id, slug="uat-proj-404", name="P")
    await api_db.add_all([proj])

    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/projects/{proj.id}/exports/uat",
            json={"case_ids": ["nonexistent-case-id"], "title": "UAT", "locale": "id"},
            headers={"X-Workspace-Id": ws.id},
        )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_uat_export_404_case_in_different_project(api_db: ApiDb) -> None:
    """A valid case that belongs to a different project → 404."""
    user = await api_db.seed_user(email="uat-cross@example.com")
    ws = await api_db.member_workspace(user, slug="uat-cross-ws")

    # project A owns the case
    proj_a = Project(workspace_id=ws.id, slug="uat-proj-a", name="A")
    proj_b = Project(workspace_id=ws.id, slug="uat-proj-b", name="B")
    await api_db.add_all([proj_a, proj_b])
    _, case = await _seed_case(api_db, ws.id, proj_a.id, public_id="TC-UAT-X")

    # POST to project B → case not in project B → 404
    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/projects/{proj_b.id}/exports/uat",
            json={"case_ids": [case.id], "title": "UAT", "locale": "id"},
            headers={"X-Workspace-Id": ws.id},
        )

    assert resp.status_code == 404
