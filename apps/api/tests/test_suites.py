"""Task 7b — suite read endpoint tests (docs/API.md §3.4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.case import TestCase
from suitest_db.models.project import Project, Suite
from suitest_shared.domain.enums import CaseSource

if TYPE_CHECKING:
    from conftest import ApiDb


@pytest.mark.asyncio
async def test_suites_list_filtered_by_project(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="suite-list@example.com")
    ws = await api_db.member_workspace(user, slug="suite-list-ws")
    proj_a = Project(workspace_id=ws.id, slug="proj-a", name="A")
    proj_b = Project(workspace_id=ws.id, slug="proj-b", name="B")
    await api_db.add_all([proj_a, proj_b])
    s_a1 = Suite(project_id=proj_a.id, name="A1", order=0)
    s_a2 = Suite(project_id=proj_a.id, name="A2", order=1)
    s_b1 = Suite(project_id=proj_b.id, name="B1", order=0)
    await api_db.add_all([s_a1, s_a2, s_b1])

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/suites?projectId={proj_a.id}", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    names = {s["name"] for s in resp.json()}
    assert names == {"A1", "A2"}


@pytest.mark.asyncio
async def test_suite_case_count_accurate(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="suite-count@example.com")
    ws = await api_db.member_workspace(user, slug="suite-count-ws")
    proj = Project(workspace_id=ws.id, slug="proj-cnt", name="Cnt")
    await api_db.add_all([proj])
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    await api_db.add_all(
        [
            TestCase(
                suite_id=suite.id,
                public_id=f"TC-{i}",
                name=f"case {i}",
                source=CaseSource.MANUAL,
            )
            for i in range(3)
        ]
    )

    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/suites/{suite.id}", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    assert resp.json()["case_count"] == 3


@pytest.mark.asyncio
async def test_suite_detail_404_when_cross_workspace(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="suite-x@example.com")
    ws = await api_db.member_workspace(user, slug="suite-x-ws")
    other = await api_db.seed_workspace(slug="suite-x-other", name="Other")
    proj = Project(workspace_id=other.id, slug="proj-x", name="X")
    await api_db.add_all([proj])
    suite = Suite(project_id=proj.id, name="X", order=0)
    await api_db.add_all([suite])

    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/suites/{suite.id}", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 404
