"""Task 7d — requirement + traceability read endpoint tests (docs/API.md §3.7)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.case import TestCase
from suitest_db.models.defect import Defect
from suitest_db.models.project import Project, Suite
from suitest_db.models.requirement import Requirement, RequirementLink
from suitest_shared.domain.enums import CaseSource, DefectStatus, Severity

if TYPE_CHECKING:
    from api_harness import ApiDb


async def _project(api_db: ApiDb, ws_id: str, *, slug: str = "req-proj") -> Project:
    proj = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([proj])
    return proj


@pytest.mark.asyncio
async def test_list_requirements_with_link_count(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="req-count@example.com")
    ws = await api_db.member_workspace(user, slug="req-count-ws")
    proj = await _project(api_db, ws.id)
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(suite_id=suite.id, public_id="TC-1", name="c", source=CaseSource.MANUAL)
    req = Requirement(project_id=proj.id, public_id="REQ-1", title="r1")
    await api_db.add_all([case, req])
    await api_db.add_all([RequirementLink(requirement_id=req.id, case_id=case.id)])

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/requirements?projectId={proj.id}", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["link_count"] == 1


@pytest.mark.asyncio
async def test_get_requirement_detail_lists_cases_and_defects(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="req-detail@example.com")
    ws = await api_db.member_workspace(user, slug="req-detail-ws")
    proj = await _project(api_db, ws.id)
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(suite_id=suite.id, public_id="TC-9", name="c", source=CaseSource.MANUAL)
    req = Requirement(project_id=proj.id, public_id="REQ-9", title="r9")
    await api_db.add_all([case, req])
    await api_db.add_all([RequirementLink(requirement_id=req.id, case_id=case.id)])
    defect = Defect(
        public_id="SUIT-9",
        workspace_id=ws.id,
        title="bug",
        severity=Severity.HIGH,
        status=DefectStatus.OPEN,
        requirement_id=req.id,
        created_by="seed",
    )
    await api_db.add_all([defect])

    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/requirements/{req.id}", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["case_public_ids"] == ["TC-9"]
    assert data["defect_public_ids"] == ["SUIT-9"]


@pytest.mark.asyncio
async def test_traceability_matrix_shape(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="matrix@example.com")
    ws = await api_db.member_workspace(user, slug="matrix-ws")
    proj = await _project(api_db, ws.id)
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    cases = [
        TestCase(suite_id=suite.id, public_id=f"TC-MX{i}", name=f"c{i}", source=CaseSource.MANUAL)
        for i in range(3)
    ]
    await api_db.add_all(cases)
    reqs = [
        Requirement(project_id=proj.id, public_id="REQ-MX1", title="r1"),
        Requirement(project_id=proj.id, public_id="REQ-MX2", title="r2"),
    ]
    await api_db.add_all(reqs)
    # 4 links: req1->case0, req1->case1, req2->case2, req2->case0
    await api_db.add_all(
        [
            RequirementLink(requirement_id=reqs[0].id, case_id=cases[0].id),
            RequirementLink(requirement_id=reqs[0].id, case_id=cases[1].id),
            RequirementLink(requirement_id=reqs[1].id, case_id=cases[2].id),
            RequirementLink(requirement_id=reqs[1].id, case_id=cases[0].id),
        ]
    )
    defects = [
        Defect(
            public_id="SUIT-MX1",
            workspace_id=ws.id,
            title="d1",
            severity=Severity.CRITICAL,
            status=DefectStatus.OPEN,
            requirement_id=reqs[0].id,
            created_by="seed",
        ),
        Defect(
            public_id="SUIT-MX2",
            workspace_id=ws.id,
            title="d2",
            severity=Severity.LOW,
            status=DefectStatus.OPEN,
            requirement_id=reqs[1].id,
            created_by="seed",
        ),
    ]
    await api_db.add_all(defects)

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/traceability/matrix?projectId={proj.id}", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["requirements"]) == 2
    assert len(data["cases"]) == 3
    assert len(data["defects"]) == 2
    req1 = next(r for r in data["requirements"] if r["id"] == "REQ-MX1")
    assert sorted(req1["tests"]) == ["TC-MX0", "TC-MX1"]
    assert req1["defects"] == ["SUIT-MX1"]


@pytest.mark.asyncio
async def test_traceability_matrix_empty_project(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="matrix-empty@example.com")
    ws = await api_db.member_workspace(user, slug="matrix-empty-ws")
    proj = await _project(api_db, ws.id)

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/traceability/matrix?projectId={proj.id}", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"requirements": [], "cases": [], "defects": []}


@pytest.mark.asyncio
async def test_requirements_list_404_cross_workspace(api_db: ApiDb) -> None:
    """Member of workspace A passing a workspace-B projectId gets 404, not its requirements."""
    user = await api_db.seed_user(email="req-xws-list@example.com")
    ws_a = await api_db.member_workspace(user, slug="req-xws-a")
    # Foreign workspace B: user is NOT a member. Seed a project + requirement in B.
    ws_b = await api_db.seed_workspace(slug="req-xws-b", name="B")
    foreign_proj = await _project(api_db, ws_b.id, slug="req-xws-foreign")
    await api_db.add_all(
        [Requirement(project_id=foreign_proj.id, public_id="REQ-XWS", title="secret")]
    )
    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/requirements?projectId={foreign_proj.id}",
            headers={"X-Workspace-Id": ws_a.id},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_traceability_matrix_404_cross_workspace(api_db: ApiDb) -> None:
    """Traceability matrix must refuse a foreign-workspace projectId with 404."""
    user = await api_db.seed_user(email="matrix-xws@example.com")
    ws_a = await api_db.member_workspace(user, slug="matrix-xws-a")
    ws_b = await api_db.seed_workspace(slug="matrix-xws-b", name="B")
    foreign_proj = await _project(api_db, ws_b.id, slug="matrix-xws-foreign")
    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/traceability/matrix?projectId={foreign_proj.id}",
            headers={"X-Workspace-Id": ws_a.id},
        )
    assert resp.status_code == 404
