"""Tests for ``GET /api/v1/runs/summary`` (CRITICAL C4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.project import Project
from suitest_db.models.run import Run
from suitest_shared.domain.enums import RunStatus, RunTrigger, Tier

if TYPE_CHECKING:
    from api_harness import ApiDb


def _run(project_id: str, public_id: str, **kw: object) -> Run:
    return Run(
        public_id=public_id,
        project_id=project_id,
        name="run",
        trigger=RunTrigger.MANUAL,
        tier_at_runtime=Tier.ZERO,
        **kw,
    )


@pytest.mark.asyncio
async def test_runs_summary_counts_by_status(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="run-sum-status@example.com")
    ws = await api_db.member_workspace(user, slug="run-sum-status-ws")
    proj = Project(workspace_id=ws.id, slug="run-sum-p", name="P")
    await api_db.add_all([proj])
    await api_db.add_all(
        [
            _run(proj.id, "RUN-SS1", status=RunStatus.PASS, duration_ms=1000),
            _run(proj.id, "RUN-SS2", status=RunStatus.PASS, duration_ms=2000),
            _run(proj.id, "RUN-SS3", status=RunStatus.FAIL, duration_ms=3000),
            _run(proj.id, "RUN-SS4", status=RunStatus.ERROR, duration_ms=4000),
            _run(proj.id, "RUN-SS5", status=RunStatus.RUNNING),
            _run(proj.id, "RUN-SS6", status=RunStatus.QUEUED),
            _run(proj.id, "RUN-SS7", status=RunStatus.QUEUED),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/runs/summary", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] == 1
    assert body["passed"] == 2
    assert body["failed"] == 2  # FAIL + ERROR
    assert body["queued"] == 2
    # Avg over the four non-null durations = (1000+2000+3000+4000)/4
    assert body["avgDurationMs"] == 2500
    # Today counts every run inserted (clock-frozen would be cleaner, but the
    # testcontainer-backed run created_at is server NOW(), so today >= 7).
    assert body["today"] >= 7


@pytest.mark.asyncio
async def test_runs_summary_workspace_isolated(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="run-sum-iso@example.com")
    ws = await api_db.member_workspace(user, slug="run-sum-iso-ws")
    other = await api_db.seed_workspace(slug="run-sum-iso-other", name="Other")
    mine = Project(workspace_id=ws.id, slug="mine", name="Mine")
    theirs = Project(workspace_id=other.id, slug="theirs", name="Theirs")
    await api_db.add_all([mine, theirs])
    await api_db.add_all(
        [
            _run(mine.id, "RUN-MINE", status=RunStatus.PASS),
            _run(theirs.id, "RUN-THEIRS-A", status=RunStatus.PASS),
            _run(theirs.id, "RUN-THEIRS-B", status=RunStatus.FAIL),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/runs/summary", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["passed"] == 1
    assert body["failed"] == 0
