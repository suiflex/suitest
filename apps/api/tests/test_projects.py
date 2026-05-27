"""Task 7b — project read endpoint tests (docs/API.md §3.2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.project import Project

if TYPE_CHECKING:
    from api_harness import ApiDb


@pytest.mark.asyncio
async def test_projects_list_paginated(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="proj-page@example.com")
    ws = await api_db.member_workspace(user, slug="proj-page-ws")
    # 25 projects → expect 10 + 10 + 5 across three pages.
    await api_db.add_all(
        [Project(workspace_id=ws.id, slug=f"p{i:02d}", name=f"P{i}") for i in range(25)]
    )

    async with api_db.client(user) as c:
        page1 = (await c.get("/api/v1/projects?limit=10", headers={"X-Workspace-Id": ws.id})).json()
        assert len(page1["items"]) == 10
        cur1 = page1["meta"]["nextCursor"]
        assert cur1 is not None

        page2 = (
            await c.get(
                f"/api/v1/projects?limit=10&cursor={cur1}", headers={"X-Workspace-Id": ws.id}
            )
        ).json()
        assert len(page2["items"]) == 10
        cur2 = page2["meta"]["nextCursor"]
        assert cur2 is not None

        page3 = (
            await c.get(
                f"/api/v1/projects?limit=10&cursor={cur2}", headers={"X-Workspace-Id": ws.id}
            )
        ).json()
    assert len(page3["items"]) == 5
    assert page3["meta"]["nextCursor"] is None
    all_ids = {p["id"] for p in page1["items"] + page2["items"] + page3["items"]}
    assert len(all_ids) == 25


@pytest.mark.asyncio
async def test_project_detail_404_when_cross_workspace(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="proj-x@example.com")
    ws = await api_db.member_workspace(user, slug="proj-x-ws")
    other = await api_db.seed_workspace(slug="proj-x-other", name="Other")
    proj = Project(workspace_id=other.id, slug="secret", name="Secret")
    await api_db.add_all([proj])

    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/projects/{proj.id}", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_projects_list_invalid_cursor_400(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="proj-badcursor@example.com")
    ws = await api_db.member_workspace(user, slug="proj-badcursor-ws")

    async with api_db.client(user) as c:
        resp = await c.get(
            "/api/v1/projects?cursor=not-a-real-cursor", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 400
