"""WorkspaceCapabilityRepo tests — upsert insert-then-update."""

from __future__ import annotations

import pytest
from factories import make_workspace
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_db.repositories.workspace_capabilities import WorkspaceCapabilityRepo
from suitest_shared.domain.enums import AutonomyLevel, Tier


@pytest.mark.asyncio
async def test_upsert_inserts_then_updates(session: AsyncSession) -> None:
    repo = WorkspaceCapabilityRepo(session)
    ws = await make_workspace(session)

    first = await repo.upsert(ws.id, Tier.ZERO, AutonomyLevel.MANUAL, {"ai": False})
    assert first.tier == Tier.ZERO
    first_id = first.id

    second = await repo.upsert(ws.id, Tier.CLOUD, AutonomyLevel.ASSIST, {"ai": True})
    assert second.id == first_id  # same row, updated in place
    assert second.tier == Tier.CLOUD
    assert second.autonomy_level == AutonomyLevel.ASSIST
    assert second.features_json == {"ai": True}

    count = await session.scalar(
        select(func.count())
        .select_from(WorkspaceCapability)
        .where(WorkspaceCapability.workspace_id == ws.id)
    )
    assert count == 1


@pytest.mark.asyncio
async def test_get(session: AsyncSession) -> None:
    repo = WorkspaceCapabilityRepo(session)
    ws = await make_workspace(session)
    assert await repo.get(ws.id) is None
    await repo.upsert(ws.id, Tier.LOCAL, AutonomyLevel.MANUAL, {})
    fetched = await repo.get(ws.id)
    assert fetched is not None
    assert fetched.tier == Tier.LOCAL
