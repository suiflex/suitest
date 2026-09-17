"""Risk-based strategy API: ZERO draft, edit, approval, and versioning."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_api.schemas.test_strategy import TestStrategyDraftRequest as StrategyDraftRequest
from suitest_api.services.test_strategy_service import TestStrategyService as StrategyService
from suitest_db.models.project import Project
from suitest_db.models.test_strategy import TestStrategy as StrategyRow
from suitest_db.repositories.test_strategies import TestStrategyRepository as StrategyRepository
from suitest_shared.domain.enums import TestingApproach as Approach
from suitest_shared.domain.enums import TestStrategyStatus as StrategyStatus

if TYPE_CHECKING:
    from api_harness import ApiDb


def test_strategy_approach_selection_without_database() -> None:
    black, _ = StrategyService._approach(StrategyDraftRequest())
    gray, _ = StrategyService._approach(StrategyDraftRequest(has_repository=True))
    white, _ = StrategyService._approach(StrategyDraftRequest(has_internal_test_provider=True))
    assert (black, gray, white) == (
        Approach.BLACK_BOX,
        Approach.GRAY_BOX,
        Approach.WHITE_BOX,
    )


@pytest.mark.asyncio
async def test_next_strategy_version_locks_project_first() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = 2
    repo = StrategyRepository(session)

    assert await repo.next_version("project-1") == 3
    statement = session.execute.await_args.args[0]
    sql = str(statement)
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
async def test_strategy_zero_draft_and_approval(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="strategy@example.com")
    workspace = await api_db.member_workspace(user, slug="strategy-workspace")
    project = Project(workspace_id=workspace.id, slug="payments", name="Payments")
    await api_db.add_all([project])
    headers = {"X-Workspace-Id": workspace.id}

    async with api_db.client(user, llm_ready=False) as client:
        created = await client.post(
            f"/api/v1/projects/{project.id}/test-strategies/draft",
            headers=headers,
            json={
                "hasRepository": True,
                "hasInternalObservability": True,
                "hasInternalTestProvider": False,
                "context": "Checkout is revenue critical.",
            },
        )
        assert created.status_code == 201, created.text
        draft = created.json()
        assert draft["status"] == "DRAFT"
        assert draft["document"]["recommended_approach"] == "GRAY_BOX"
        assert draft["document"]["qa_checks"]
        assert draft["document"]["risks"]

        approved = await client.post(
            f"/api/v1/test-strategies/{draft['id']}/approve",
            headers=headers,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "APPROVED"

        second = await client.post(
            f"/api/v1/projects/{project.id}/test-strategies/draft",
            headers=headers,
            json={"hasInternalTestProvider": True},
        )
        second_id = second.json()["id"]
        second_approved = await client.post(
            f"/api/v1/test-strategies/{second_id}/approve",
            headers=headers,
        )
        assert second_approved.status_code == 200
        assert second_approved.json()["document"]["recommended_approach"] == "WHITE_BOX"

    async with api_db.maker() as session:
        rows = list(
            (
                await session.scalars(
                    select(StrategyRow)
                    .where(StrategyRow.project_id == project.id)
                    .order_by(StrategyRow.version)
                )
            ).all()
        )
        assert [row.version for row in rows] == [1, 2]
        assert [row.status for row in rows] == [
            StrategyStatus.SUPERSEDED,
            StrategyStatus.APPROVED,
        ]


@pytest.mark.asyncio
async def test_strategy_enrichment_requires_llm(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="strategy-nollm@example.com")
    workspace = await api_db.member_workspace(user, slug="strategy-nollm")
    project = Project(workspace_id=workspace.id, slug="catalog", name="Catalog")
    await api_db.add_all([project])
    headers = {"X-Workspace-Id": workspace.id}

    async with api_db.client(user, llm_ready=False) as client:
        created = await client.post(
            f"/api/v1/projects/{project.id}/test-strategies/draft",
            headers=headers,
            json={},
        )
        response = await client.post(
            f"/api/v1/test-strategies/{created.json()['id']}/enrich",
            headers=headers,
        )
    assert response.status_code == 409
