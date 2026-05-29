"""Tests for ``GET /api/v1/runs/:id/logs`` cursor pagination (M1c Task 17).

Seeds 500 rows with monotonic ``seq``, then walks the pages: 200 → 200 → 100.
The third page returns fewer than ``limit`` items, so ``hasMore`` is false.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.project import Project
from suitest_db.models.run import Run
from suitest_db.models.run_step_log import RunStepLog
from suitest_shared.domain.enums import RunTrigger, Tier

if TYPE_CHECKING:
    from api_harness import ApiDb


@pytest.mark.asyncio
async def test_logs_paginate_500(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="run-logs-page@example.com")
    ws = await api_db.member_workspace(user, slug="run-logs-page-ws")
    proj = Project(workspace_id=ws.id, slug="run-logs-page-p", name="P")
    await api_db.add_all([proj])
    run = Run(
        public_id="RUN-LOGS-500",
        project_id=proj.id,
        name="r",
        trigger=RunTrigger.MANUAL,
        tier_at_runtime=Tier.ZERO,
    )
    await api_db.add_all([run])

    # Bulk-seed 500 rows with monotonic seq 1..500. Done in chunks of 100 so
    # the testcontainer Postgres roundtrip stays brisk on slow CI runners.
    for start in range(1, 501, 100):
        await api_db.add_all(
            [
                RunStepLog(run_id=run.id, seq=s, level="info", message=f"m{s}")
                for s in range(start, start + 100)
            ]
        )

    async with api_db.client(user) as c:
        page1 = (
            await c.get(
                f"/api/v1/runs/{run.id}/logs?cursor=0&limit=200",
                headers={"X-Workspace-Id": ws.id},
            )
        ).json()
        page2 = (
            await c.get(
                f"/api/v1/runs/{run.id}/logs?cursor={page1['nextCursor']}&limit=200",
                headers={"X-Workspace-Id": ws.id},
            )
        ).json()
        page3 = (
            await c.get(
                f"/api/v1/runs/{run.id}/logs?cursor={page2['nextCursor']}&limit=200",
                headers={"X-Workspace-Id": ws.id},
            )
        ).json()

    assert len(page1["items"]) == 200
    assert len(page2["items"]) == 200
    assert len(page3["items"]) == 100
    assert page3["hasMore"] is False
    # Sanity: pages cover seq 1..500 in order without gaps / overlaps.
    seqs = [it["seq"] for it in page1["items"] + page2["items"] + page3["items"]]
    assert seqs == list(range(1, 501))
