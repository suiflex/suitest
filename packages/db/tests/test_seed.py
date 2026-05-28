"""Tests for the Nusantara Retail seed script (Task 9).

The seeder is exercised against the shared pgvector testcontainer via the
``session`` fixture. Every test commits at the end of ``run_all`` so the
re-run idempotency check below can confirm row counts converge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select
from suitest_db.models.case import TestCase
from suitest_db.models.defect import Defect
from suitest_db.models.integration import Integration
from suitest_db.models.requirement import Requirement, RequirementLink
from suitest_db.models.run import Run
from suitest_db.models.workspace import Workspace
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_db.seed import (
    WORKSPACE_NAME,
    WORKSPACE_SLUG,
    Seeder,
)
from suitest_shared.domain.enums import (
    AutonomyLevel,
    RunStatus,
    Tier,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _row_counts(session: AsyncSession) -> dict[str, int]:
    """Snapshot the counts the idempotency test cares about."""
    out: dict[str, int] = {}
    for label, model in (
        ("workspaces", Workspace),
        ("test_cases", TestCase),
        ("runs", Run),
        ("defects", Defect),
        ("integrations", Integration),
        ("requirements", Requirement),
        ("requirement_links", RequirementLink),
    ):
        n = await session.scalar(select(func.count()).select_from(model))
        out[label] = int(n or 0)
    return out


@pytest.mark.asyncio
async def test_seed_idempotent(session: AsyncSession) -> None:
    """Second seeder run leaves every counted table unchanged."""
    await Seeder(session).run_all()
    await session.commit()
    first = await _row_counts(session)

    await Seeder(session).run_all()
    await session.commit()
    second = await _row_counts(session)

    assert first == second


@pytest.mark.asyncio
async def test_seed_workspace_shape(session: AsyncSession) -> None:
    await Seeder(session).run_all()
    await session.commit()

    ws = await session.scalar(select(Workspace).where(Workspace.slug == WORKSPACE_SLUG))
    assert ws is not None
    assert ws.name == WORKSPACE_NAME


@pytest.mark.asyncio
async def test_seed_eighteen_cases(session: AsyncSession) -> None:
    await Seeder(session).run_all()
    await session.commit()

    count = await session.scalar(select(func.count()).select_from(TestCase))
    assert count == 18


@pytest.mark.asyncio
async def test_seed_five_runs_with_correct_outcomes(session: AsyncSession) -> None:
    await Seeder(session).run_all()
    await session.commit()

    rows = list((await session.scalars(select(Run))).all())
    assert len(rows) == 5
    by_status: dict[RunStatus, int] = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    assert by_status.get(RunStatus.PASS) == 2
    assert by_status.get(RunStatus.FAIL) == 2
    assert by_status.get(RunStatus.ERROR) == 1
    # All runs captured tier_at_runtime=ZERO (CLAUDE.md ZERO-tier-first).
    assert all(r.tier_at_runtime == Tier.ZERO for r in rows)


@pytest.mark.asyncio
async def test_seed_three_defects(session: AsyncSession) -> None:
    await Seeder(session).run_all()
    await session.commit()

    count = await session.scalar(select(func.count()).select_from(Defect))
    assert count == 3


@pytest.mark.asyncio
async def test_seed_nine_integrations_mixed_status(session: AsyncSession) -> None:
    await Seeder(session).run_all()
    await session.commit()

    rows = list((await session.scalars(select(Integration))).all())
    assert len(rows) == 9
    active = sum(1 for r in rows if r.status == "active")
    disconnected = sum(1 for r in rows if r.status == "disconnected")
    assert active + disconnected == 9
    assert active >= 1 and disconnected >= 1
    # Active integrations carry an encrypted secret, disconnected ones do not.
    for r in rows:
        if r.status == "active":
            assert r.secrets_encrypted is not None
        else:
            assert r.secrets_encrypted is None


@pytest.mark.asyncio
async def test_seed_capability_zero_manual(session: AsyncSession) -> None:
    await Seeder(session).run_all()
    await session.commit()

    cap = await session.scalar(select(WorkspaceCapability))
    assert cap is not None
    assert cap.tier == Tier.ZERO
    assert cap.autonomy_level == AutonomyLevel.MANUAL
