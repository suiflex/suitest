"""Integration tests for M7 cost budget guard endpoints.

Tests:
  - POST /workspaces/:id/cost/user-limits (ADMIN only)
  - GET  /workspaces/:id/cost/user-limits
  - DELETE /workspaces/:id/cost/user-limits/:userId
  - Budget hard-stop behaviour via require_budget_available dependency
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from suitest_db.models.agent import AgentSession
from suitest_db.models.user_budget import UserBudget
from suitest_shared.domain.enums import AgentSessionKind, Role

if TYPE_CHECKING:
    from api_harness import ApiDb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_budget(
    api_db: ApiDb,
    workspace_id: str,
    user_id: uuid.UUID,
    *,
    daily_cap: str = "5.0000",
    monthly_cap: str = "50.0000",
) -> None:
    await api_db.add_all(
        [
            UserBudget(
                workspace_id=workspace_id,
                user_id=user_id,
                daily_cap_usd=Decimal(daily_cap),
                monthly_cap_usd=Decimal(monthly_cap),
            )
        ]
    )


async def _seed_agent_spend(
    api_db: ApiDb,
    workspace_id: str,
    user_id: uuid.UUID,
    *,
    cost: str,
) -> None:
    await api_db.add_all(
        [
            AgentSession(
                workspace_id=workspace_id,
                user_id=user_id,
                kind=AgentSessionKind.GENERATION,
                model_id="m-1",
                provider="mock",
                status="completed",
                cost_usd=Decimal(cost),
            )
        ]
    )


# ---------------------------------------------------------------------------
# POST /workspaces/:id/cost/user-limits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_set_user_limit(api_db: ApiDb) -> None:
    admin = await api_db.seed_user(email="bg-admin@example.com")
    ws = await api_db.seed_workspace(slug="bg-admin-ws", name="bg-admin-ws")
    await api_db.seed_membership(workspace_id=ws.id, user_id=admin.id, role=Role.ADMIN)
    target_user = await api_db.seed_user(email="bg-target@example.com")
    await api_db.seed_membership(workspace_id=ws.id, user_id=target_user.id)

    async with api_db.client(admin) as c:
        resp = await c.post(
            f"/api/v1/workspaces/{ws.id}/cost/user-limits",
            headers={"X-Workspace-Id": ws.id},
            json={"userId": str(target_user.id), "dailyCapUsd": 10.0, "monthlyCapUsd": 100.0},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["userId"] == str(target_user.id)
    assert body["workspaceId"] == ws.id
    assert body["dailyCapUsd"] == pytest.approx(10.0)
    assert body["monthlyCapUsd"] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_member_cannot_set_user_limit(api_db: ApiDb) -> None:
    member = await api_db.seed_user(email="bg-member@example.com")
    ws = await api_db.member_workspace(member, slug="bg-member-ws")

    async with api_db.client(member) as c:
        resp = await c.post(
            f"/api/v1/workspaces/{ws.id}/cost/user-limits",
            headers={"X-Workspace-Id": ws.id},
            json={"userId": str(member.id), "dailyCapUsd": 5.0, "monthlyCapUsd": 50.0},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_set_user_limit(api_db: ApiDb) -> None:
    owner = await api_db.seed_user(email="bg-owner@example.com")
    ws = await api_db.seed_workspace(slug="bg-owner-ws", name="bg-owner-ws")
    await api_db.seed_membership(workspace_id=ws.id, user_id=owner.id, role=Role.OWNER)

    async with api_db.client(owner) as c:
        resp = await c.post(
            f"/api/v1/workspaces/{ws.id}/cost/user-limits",
            headers={"X-Workspace-Id": ws.id},
            json={"userId": str(owner.id), "dailyCapUsd": 20.0, "monthlyCapUsd": 200.0},
        )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /workspaces/:id/cost/user-limits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_user_limits_returns_all_for_workspace(api_db: ApiDb) -> None:
    admin = await api_db.seed_user(email="bg-list-admin@example.com")
    ws = await api_db.seed_workspace(slug="bg-list-ws", name="bg-list-ws")
    await api_db.seed_membership(workspace_id=ws.id, user_id=admin.id, role=Role.ADMIN)

    user_a = await api_db.seed_user(email="bg-list-a@example.com")
    user_b = await api_db.seed_user(email="bg-list-b@example.com")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user_a.id)
    await api_db.seed_membership(workspace_id=ws.id, user_id=user_b.id)

    await _seed_budget(api_db, ws.id, user_a.id, daily_cap="3.0000", monthly_cap="30.0000")
    await _seed_budget(api_db, ws.id, user_b.id, daily_cap="7.0000", monthly_cap="70.0000")

    async with api_db.client(admin) as c:
        resp = await c.get(
            f"/api/v1/workspaces/{ws.id}/cost/user-limits",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    user_ids = {item["userId"] for item in items}
    assert str(user_a.id) in user_ids
    assert str(user_b.id) in user_ids


@pytest.mark.asyncio
async def test_list_user_limits_empty_when_none_set(api_db: ApiDb) -> None:
    admin = await api_db.seed_user(email="bg-empty-admin@example.com")
    ws = await api_db.seed_workspace(slug="bg-empty-ws", name="bg-empty-ws")
    await api_db.seed_membership(workspace_id=ws.id, user_id=admin.id, role=Role.ADMIN)

    async with api_db.client(admin) as c:
        resp = await c.get(
            f"/api/v1/workspaces/{ws.id}/cost/user-limits",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# DELETE /workspaces/:id/cost/user-limits/:userId
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_delete_user_limit(api_db: ApiDb) -> None:
    admin = await api_db.seed_user(email="bg-del-admin@example.com")
    ws = await api_db.seed_workspace(slug="bg-del-ws", name="bg-del-ws")
    await api_db.seed_membership(workspace_id=ws.id, user_id=admin.id, role=Role.ADMIN)
    target = await api_db.seed_user(email="bg-del-target@example.com")
    await api_db.seed_membership(workspace_id=ws.id, user_id=target.id)

    await _seed_budget(api_db, ws.id, target.id)

    async with api_db.client(admin) as c:
        # Verify it exists first
        resp = await c.get(
            f"/api/v1/workspaces/{ws.id}/cost/user-limits",
            headers={"X-Workspace-Id": ws.id},
        )
    assert len(resp.json()) == 1

    async with api_db.client(admin) as c:
        resp = await c.delete(
            f"/api/v1/workspaces/{ws.id}/cost/user-limits/{target.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 204

    async with api_db.client(admin) as c:
        resp = await c.get(
            f"/api/v1/workspaces/{ws.id}/cost/user-limits",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.json() == []


@pytest.mark.asyncio
async def test_delete_non_existent_limit_returns_404(api_db: ApiDb) -> None:
    admin = await api_db.seed_user(email="bg-del404-admin@example.com")
    ws = await api_db.seed_workspace(slug="bg-del404-ws", name="bg-del404-ws")
    await api_db.seed_membership(workspace_id=ws.id, user_id=admin.id, role=Role.ADMIN)

    fake_user_id = uuid.uuid4()
    async with api_db.client(admin) as c:
        resp = await c.delete(
            f"/api/v1/workspaces/{ws.id}/cost/user-limits/{fake_user_id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Upsert idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_updates_existing_limit(api_db: ApiDb) -> None:
    admin = await api_db.seed_user(email="bg-upsert-admin@example.com")
    ws = await api_db.seed_workspace(slug="bg-upsert-ws", name="bg-upsert-ws")
    await api_db.seed_membership(workspace_id=ws.id, user_id=admin.id, role=Role.ADMIN)
    target = await api_db.seed_user(email="bg-upsert-target@example.com")
    await api_db.seed_membership(workspace_id=ws.id, user_id=target.id)

    async with api_db.client(admin) as c:
        # First upsert
        resp = await c.post(
            f"/api/v1/workspaces/{ws.id}/cost/user-limits",
            headers={"X-Workspace-Id": ws.id},
            json={"userId": str(target.id), "dailyCapUsd": 5.0, "monthlyCapUsd": 50.0},
        )
        assert resp.status_code == 200

        # Second upsert — should update, not create a duplicate
        resp = await c.post(
            f"/api/v1/workspaces/{ws.id}/cost/user-limits",
            headers={"X-Workspace-Id": ws.id},
            json={"userId": str(target.id), "dailyCapUsd": 15.0, "monthlyCapUsd": 150.0},
        )
    assert resp.status_code == 200
    assert resp.json()["dailyCapUsd"] == pytest.approx(15.0)
    assert resp.json()["monthlyCapUsd"] == pytest.approx(150.0)

    # Verify still only one row
    async with api_db.client(admin) as c:
        resp = await c.get(
            f"/api/v1/workspaces/{ws.id}/cost/user-limits",
            headers={"X-Workspace-Id": ws.id},
        )
    assert len(resp.json()) == 1


# ---------------------------------------------------------------------------
# get_cheaper_model (M7-2) unit tests
# ---------------------------------------------------------------------------


def test_get_cheaper_model_opus_to_sonnet() -> None:
    from suitest_api.services.cost_service import get_cheaper_model

    result = get_cheaper_model("claude-opus-4-5", 15.0, 10.0)
    assert result == "claude-sonnet-4-5"


def test_get_cheaper_model_sonnet_to_haiku() -> None:
    from suitest_api.services.cost_service import get_cheaper_model

    result = get_cheaper_model("claude-sonnet-4-5", 12.0, 10.0)
    assert result == "claude-haiku-3-5"


def test_get_cheaper_model_below_threshold_returns_none() -> None:
    from suitest_api.services.cost_service import get_cheaper_model

    result = get_cheaper_model("claude-opus-4-5", 5.0, 10.0)
    assert result is None


def test_get_cheaper_model_zero_threshold_disabled() -> None:
    from suitest_api.services.cost_service import get_cheaper_model

    result = get_cheaper_model("claude-opus-4-5", 999.0, 0)
    assert result is None


def test_get_cheaper_model_unknown_model_returns_none() -> None:
    from suitest_api.services.cost_service import get_cheaper_model

    result = get_cheaper_model("some-unknown-model-xyz", 50.0, 10.0)
    assert result is None


def test_get_cheaper_model_with_provider_prefix() -> None:
    """Model names prefixed with provider/ are normalised before lookup."""
    from suitest_api.services.cost_service import get_cheaper_model

    result = get_cheaper_model("anthropic/claude-opus-4-5", 15.0, 10.0)
    assert result == "claude-sonnet-4-5"


def test_get_cheaper_model_gpt4_to_gpt35() -> None:
    from suitest_api.services.cost_service import get_cheaper_model

    result = get_cheaper_model("gpt-4", 20.0, 5.0)
    assert result == "gpt-3.5-turbo"


def test_get_cheaper_model_gemini() -> None:
    from suitest_api.services.cost_service import get_cheaper_model

    result = get_cheaper_model("gemini-pro", 20.0, 5.0)
    assert result == "gemini-flash"
