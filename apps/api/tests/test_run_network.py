"""Tests for ``GET /api/v1/runs/:id/network`` (CRITICAL C4 stub)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.project import Project
from suitest_db.models.run import Run
from suitest_shared.domain.enums import RunTrigger, Tier

if TYPE_CHECKING:
    from api_harness import ApiDb


def _run(project_id: str, public_id: str) -> Run:
    return Run(
        public_id=public_id,
        project_id=project_id,
        name="run",
        trigger=RunTrigger.MANUAL,
        tier_at_runtime=Tier.ZERO,
    )


@pytest.mark.asyncio
async def test_run_network_returns_empty_stub(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="run-net@example.com")
    ws = await api_db.member_workspace(user, slug="run-net-ws")
    proj = Project(workspace_id=ws.id, slug="run-net-p", name="P")
    await api_db.add_all([proj])
    run = _run(proj.id, "RUN-NET")
    await api_db.add_all([run])

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/runs/{run.id}/network",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


@pytest.mark.asyncio
async def test_run_network_404_cross_workspace(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="run-net-x@example.com")
    ws = await api_db.member_workspace(user, slug="run-net-x-ws")
    other = await api_db.seed_workspace(slug="run-net-x-other", name="Other")
    proj = Project(workspace_id=other.id, slug="run-net-x-p", name="P")
    await api_db.add_all([proj])
    run = _run(proj.id, "RUN-NET-X")
    await api_db.add_all([run])

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/runs/{run.id}/network",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404
