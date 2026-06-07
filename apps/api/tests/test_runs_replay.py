"""Tests for time-travel replay state delta (M5-1).

Two layers: a pure unit test of :func:`compute_state_delta` (no DB) and an
endpoint test that seeds a run with two steps carrying ``state_snapshot`` and
asserts the second step's delta reflects added/removed/changed keys.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_api.services.replay_service import compute_state_delta
from suitest_db.models.case import TestCase
from suitest_db.models.project import Project, Suite
from suitest_db.models.run import Run, RunStep
from suitest_shared.domain.enums import CaseSource, RunTrigger, StepOutcome, Tier

if TYPE_CHECKING:
    from api_harness import ApiDb


def test_compute_state_delta_added_removed_changed() -> None:
    prev = {"url": "/a", "count": 1, "gone": True}
    cur = {"url": "/b", "count": 1, "added": "x"}
    delta = compute_state_delta(prev, cur)
    ops = {(c.path, c.op) for c in delta}
    assert ("url", "changed") in ops
    assert ("gone", "removed") in ops
    assert ("added", "added") in ops
    # Unchanged key omitted.
    assert all(c.path != "count" for c in delta)


def test_compute_state_delta_first_step_empty() -> None:
    delta = compute_state_delta(None, {"x": 1})
    assert len(delta) == 1
    assert delta[0].op == "added"
    assert delta[0].path == "x"


def test_compute_state_delta_nested_paths() -> None:
    delta = compute_state_delta({"a": {"b": 1}}, {"a": {"b": 2}})
    assert len(delta) == 1
    assert delta[0].path == "a.b"
    assert delta[0].op == "changed"


@pytest.mark.asyncio
async def test_replay_endpoint_returns_per_step_delta(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="replay@example.com")
    ws = await api_db.member_workspace(user, slug="replay-ws")
    proj = Project(workspace_id=ws.id, slug="replay-p", name="P")
    await api_db.add_all([proj])
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(suite_id=suite.id, public_id="TC-REPLAY", name="c", source=CaseSource.MANUAL)
    await api_db.add_all([case])
    run = Run(
        public_id="RUN-REPLAY",
        project_id=proj.id,
        name="r",
        trigger=RunTrigger.MANUAL,
        tier_at_runtime=Tier.ZERO,
    )
    await api_db.add_all([run])
    await api_db.add_all(
        [
            RunStep(
                run_id=run.id,
                case_id=case.id,
                step_order=0,
                outcome=StepOutcome.PASS,
                state_snapshot={"url": "/login", "loggedIn": False},
            ),
            RunStep(
                run_id=run.id,
                case_id=case.id,
                step_order=1,
                outcome=StepOutcome.PASS,
                state_snapshot={"url": "/dashboard", "loggedIn": True},
            ),
        ]
    )

    async with api_db.client(user) as c:
        body = (
            await c.get(
                f"/api/v1/runs/{run.id}/replay",
                headers={"X-Workspace-Id": ws.id},
            )
        ).json()

    steps = body["steps"]
    assert len(steps) == 2
    # First step has no prior state → snapshot keys appear as additions.
    assert {ch["op"] for ch in steps[0]["delta"]} == {"added"}
    # Second step: url + loggedIn changed, nothing else.
    second = {ch["path"]: ch["op"] for ch in steps[1]["delta"]}
    assert second == {"url": "changed", "loggedIn": "changed"}
