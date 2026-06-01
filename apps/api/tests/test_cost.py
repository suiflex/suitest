"""Tests for ``GET /api/v1/workspaces/:id/cost`` (M3-14)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from suitest_db.models.agent import AgentSession
from suitest_db.models.llm_config import LLMConfig
from suitest_shared.domain.enums import AgentSessionKind

if TYPE_CHECKING:
    from api_harness import ApiDb


async def _session_row(
    api_db: ApiDb,
    ws_id: str,
    *,
    provider: str,
    kind: AgentSessionKind,
    cost: str,
    tokens_in: int = 100,
    tokens_out: int = 50,
) -> None:
    await api_db.add_all(
        [
            AgentSession(
                workspace_id=ws_id,
                kind=kind,
                model_id="m-1",
                provider=provider,
                status="completed",
                cost_usd=Decimal(cost),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        ]
    )


@pytest.mark.asyncio
async def test_cost_aggregates_by_provider_and_kind(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="cost-agg@example.com")
    ws = await api_db.member_workspace(user, slug="cost-agg-ws")
    await _session_row(
        api_db, ws.id, provider="mock", kind=AgentSessionKind.GENERATION, cost="0.01"
    )
    await _session_row(
        api_db, ws.id, provider="mock", kind=AgentSessionKind.GENERATION, cost="0.02"
    )
    await _session_row(
        api_db, ws.id, provider="anthropic", kind=AgentSessionKind.DIAGNOSIS, cost="0.05"
    )

    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/workspaces/{ws.id}/cost", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sessionCount"] == 3
    assert body["totalCostUsd"] == pytest.approx(0.08)
    assert body["totalTokensIn"] == 300

    by_provider = {p["provider"]: p for p in body["byProvider"]}
    assert by_provider["mock"]["costUsd"] == pytest.approx(0.03)
    assert by_provider["mock"]["sessions"] == 2
    assert by_provider["anthropic"]["costUsd"] == pytest.approx(0.05)

    by_kind = {k["kind"]: k for k in body["byKind"]}
    assert by_kind["GENERATION"]["sessions"] == 2
    assert by_kind["DIAGNOSIS"]["sessions"] == 1


@pytest.mark.asyncio
async def test_cost_soft_budget_alert_when_over_cap(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="cost-budget@example.com")
    ws = await api_db.member_workspace(user, slug="cost-budget-ws")
    # A tiny daily cap so a single cheap session trips the soft alert.
    await api_db.add_all(
        [
            LLMConfig(
                workspace_id=ws.id,
                provider="mock",
                model="m-1",
                api_key_encrypted=None,
                config_json={"daily_cap_usd": 0.001},
                is_active=True,
            )
        ]
    )
    await _session_row(
        api_db, ws.id, provider="mock", kind=AgentSessionKind.GENERATION, cost="0.01"
    )

    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/workspaces/{ws.id}/cost", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200, resp.text
    budget = resp.json()["budget"]
    assert budget["dailyCapUsd"] == pytest.approx(0.001)
    assert budget["overBudget"] is True
    assert budget["alert"] is not None


@pytest.mark.asyncio
async def test_cost_empty_workspace_zero(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="cost-empty@example.com")
    ws = await api_db.member_workspace(user, slug="cost-empty-ws")
    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/workspaces/{ws.id}/cost", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sessionCount"] == 0
    assert body["totalCostUsd"] == 0.0
    assert body["budget"]["overBudget"] is False
    assert body["budget"]["dailyCapUsd"] == pytest.approx(50.0)  # default cap
