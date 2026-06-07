"""Tests for the M5-2 eval dashboard endpoints.

``GET /eval/fixtures`` lists the bundled golden datasets; ``GET /eval/runs``
returns the score-regression history (computing ``scorePct`` per run). Both are
ADMIN+ gated. A QA member gets 403.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_shared.domain.enums import Role

if TYPE_CHECKING:
    from api_harness import ApiDb


@pytest.mark.asyncio
async def test_fixtures_lists_golden_datasets(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="eval-admin@example.com")
    ws = await api_db.seed_workspace(slug="eval-fix-ws", name="Eval Fix WS")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.ADMIN)

    async with api_db.client(user) as c:
        res = await c.get("/api/v1/eval/fixtures", headers={"X-Workspace-Id": ws.id})

    assert res.status_code == 200
    items = res.json()["items"]
    suites = {it["suite"]: it["fixtures"] for it in items}
    assert suites == {"prds": 20, "openapi": 10, "failed_runs": 15}


@pytest.mark.asyncio
async def test_runs_history_after_create_has_score_pct(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="eval-admin2@example.com")
    ws = await api_db.seed_workspace(slug="eval-runs-ws", name="Eval Runs WS")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.ADMIN)

    async with api_db.client(user) as c:
        headers = {"X-Workspace-Id": ws.id}
        # Empty history first.
        empty = await c.get("/api/v1/eval/runs", headers=headers)
        assert empty.status_code == 200
        assert empty.json()["items"] == []
        # Run the deterministic suite, then it shows up newest-first with a score.
        created = await c.post("/api/v1/eval/runs", json={"suite_name": "t"}, headers=headers)
        assert created.status_code == 201
        listed = await c.get("/api/v1/eval/runs", headers=headers)

    items = listed.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["scorePct"] == 100.0
    assert row["passed"] == row["fixturesCount"] == 45


@pytest.mark.asyncio
async def test_runs_forbidden_for_qa(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="eval-qa@example.com")
    ws = await api_db.member_workspace(user, slug="eval-qa-ws")  # QA role by default

    async with api_db.client(user) as c:
        res = await c.get("/api/v1/eval/runs", headers={"X-Workspace-Id": ws.id})

    assert res.status_code == 403
