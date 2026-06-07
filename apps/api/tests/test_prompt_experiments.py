"""Tests for the M5-4 prompt A/B testing harness.

Pure: ``choose_variant`` is deterministic and ratio-preserving. Endpoint: an
ADMIN starts an experiment (file default A vs. a fork B); ``resolve_and_pin``
routes impressions across variants and records them; outcomes accumulate and a
winner is declared.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_api.services.prompt_experiment_service import choose_variant
from suitest_api.services.prompt_resolver import resolve_and_pin
from suitest_db.repositories.prompt_experiments import PromptExperimentRepo
from suitest_db.repositories.workspace_prompt_overrides import WorkspacePromptOverrideRepo
from suitest_shared.domain.enums import Role

if TYPE_CHECKING:
    from api_harness import ApiDb


def test_choose_variant_extremes_and_split() -> None:
    assert choose_variant(0, 0, 0) == "A"
    assert choose_variant(0, 0, 100) == "B"
    # 50/50 converges: from an even state the next impression goes to B.
    assert choose_variant(1, 0, 50) == "B"
    assert choose_variant(1, 1, 50) == "A"


def test_choose_variant_ratio_preserving_over_many() -> None:
    a = b = 0
    for _ in range(100):
        if choose_variant(a, b, 30) == "B":
            b += 1
        else:
            a += 1
    # ~30% of impressions to B (within rounding).
    assert 28 <= b <= 32


@pytest.mark.asyncio
async def test_experiment_routes_and_picks_winner(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="ab-admin@example.com")
    ws = await api_db.seed_workspace(slug="ab-ws", name="AB WS")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.ADMIN)
    headers = {"X-Workspace-Id": ws.id}
    forked = "FORKED variant B content\n"

    async with api_db.client(user) as c:
        # B is a fork; A is the file default.
        fork = await c.post(
            "/api/v1/prompts/generate-from-prd/forks",
            json={"content": forked, "label": "B", "activate": False},
            headers=headers,
        )
        b_override_id = fork.json()["id"]
        created = await c.post(
            "/api/v1/prompt-experiments",
            json={
                "prompt_name": "generate-from-prd",
                "variant_a_override_id": None,
                "variant_b_override_id": b_override_id,
                "split_pct": 50,
            },
            headers=headers,
        )
        assert created.status_code == 201
        exp_id = created.json()["id"]

    # Drive a handful of resolutions; impressions split across both variants.
    async with api_db.maker() as session:
        for _ in range(6):
            await resolve_and_pin(session, workspace_id=ws.id, prompt_name="generate-from-prd")
        await session.commit()
        exp = await PromptExperimentRepo(session).get_by_id(exp_id)
        assert exp is not None
        assert exp.a_impressions + exp.b_impressions == 6
        assert exp.a_impressions > 0 and exp.b_impressions > 0

    async with api_db.client(user) as c:
        # Record B as the stronger variant, then it wins.
        await c.post(
            f"/api/v1/prompt-experiments/{exp_id}/outcome",
            json={"variant": "B", "success": True},
            headers=headers,
        )
        listed = await c.get("/api/v1/prompt-experiments", headers=headers)

    row = listed.json()["items"][0]
    assert row["winner"] == "B"

    # A fork that is also a live default override still resolves to a variant.
    async with api_db.maker() as session:
        active = await WorkspacePromptOverrideRepo(session).get_active(ws.id, "generate-from-prd")
        # The fork was created with activate=False, so no active fork — experiment drives it.
        assert active is None
