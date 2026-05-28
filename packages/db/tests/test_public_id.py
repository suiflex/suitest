"""Tests for the per-workspace per-prefix public-ID generator (Task 8).

The :func:`generate_public_id` plpgsql function (installed by Alembic revision
``0014_public_id_function``) creates one Postgres sequence per
``(workspace, prefix)`` pair on first use, starting at 1000. The
``before_insert`` listeners in :mod:`suitest_db.public_id` call that function
from each model's flush event so ``public_id`` columns get filled
transparently.

Sequences are **autonomous** in PG (CREATE SEQUENCE/nextval commit outside the
surrounding transaction), so isolating tests by rollback is not enough — every
test must run against a freshly created ``workspace_id`` to get its own
sequences. Each test below uses :func:`make_workspace`, which generates a
unique workspace row per call, guaranteeing fresh sequences.
"""

from __future__ import annotations

import pytest
from factories import make_project, make_suite, make_workspace
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.case import TestCase
from suitest_db.public_id import generate_public_id, set_workspace_id
from suitest_db.repositories.runs import RunCreate, RunRepo
from suitest_db.repositories.test_cases import TestCaseCreate, TestCaseRepo
from suitest_shared.domain.enums import CaseSource, RunTrigger, Tier


@pytest.mark.asyncio
async def test_generate_public_id_increments_per_workspace_prefix(
    session: AsyncSession,
) -> None:
    """Sequences are per-(workspace, prefix); each starts at 1000.

    ws_A receives 3 inserted cases (TC-1000/1001/1002 — listener-driven) plus a
    run (R-1000 — separate prefix). ws_B's independent sequence is exercised via
    the :func:`generate_public_id` wrapper instead of an INSERT because the
    ``test_cases.public_id`` UNIQUE index is currently table-global (added in
    revision 0005), so inserting a colliding ``TC-1000`` from ws_B would fail
    the constraint even though the sequence itself is per-workspace. The
    wrapper still proves the sequence is independent (returns 1000 for ws_B).
    """
    ws_a = await make_workspace(session, name="WS-A")
    ws_b = await make_workspace(session, name="WS-B")
    project_a = await make_project(session, workspace=ws_a)
    suite_a = await make_suite(session, project=project_a)

    case_repo = TestCaseRepo(session)

    # 3 cases in ws_A → TC-1000, TC-1001, TC-1002 (listener-assigned).
    pids_a: list[str] = []
    for n in range(3):
        case = await case_repo.create(
            TestCaseCreate(suite_id=suite_a.id, name=f"A-{n}", source=CaseSource.MANUAL),
            workspace_id=ws_a.id,
        )
        pids_a.append(case.public_id)
    assert pids_a == ["TC-1000", "TC-1001", "TC-1002"]

    # ws_B's TC sequence is independent → 1000 (verified via the async wrapper,
    # see the docstring for why we don't INSERT here).
    pid_b = await generate_public_id(session, "TC", ws_b.id)
    assert pid_b == "TC-1000"

    # 1 run in ws_A → R-1000 (separate prefix gets its own sequence even
    # within the same workspace).
    run_repo = RunRepo(session)
    run_a = await run_repo.create(
        RunCreate(
            project_id=project_a.id,
            name="run-0",
            trigger=RunTrigger.MANUAL,
            tier_at_runtime=Tier.ZERO,
        ),
        workspace_id=ws_a.id,
    )
    assert run_a.public_id == "R-1000"


@pytest.mark.asyncio
async def test_generate_public_id_missing_workspace_raises(
    session: AsyncSession,
) -> None:
    """Inserting without ``_workspace_id_for_pubid`` is a programmer error."""
    ws = await make_workspace(session, name="WS-Missing")
    project = await make_project(session, workspace=ws)
    suite = await make_suite(session, project=project)

    case = TestCase(suite_id=suite.id, name="orphan", source=CaseSource.MANUAL)
    session.add(case)
    with pytest.raises(RuntimeError, match=r"_workspace_id_for_pubid"):
        await session.flush()
    # Roll back the failed flush so the session is reusable; the outer fixture
    # also rolls back at teardown but we don't want to leave a pending flush.
    await session.rollback()


@pytest.mark.asyncio
async def test_generate_public_id_idempotent_when_already_set(
    session: AsyncSession,
) -> None:
    """A pre-set ``public_id`` is left alone (seeders / migrations may pin IDs)."""
    ws = await make_workspace(session, name="WS-Idem")
    project = await make_project(session, workspace=ws)
    suite = await make_suite(session, project=project)

    pinned = "TC-9999"
    case = TestCase(
        suite_id=suite.id,
        name="pinned",
        source=CaseSource.MANUAL,
        public_id=pinned,
    )
    # Even when the transient attr is set, the listener early-returns because
    # ``public_id`` is already populated.
    set_workspace_id(case, ws.id)
    session.add(case)
    await session.flush()

    assert case.public_id == pinned


@pytest.mark.asyncio
async def test_generate_public_id_async_wrapper(session: AsyncSession) -> None:
    """The async wrapper calls the function directly (used outside of INSERTs)."""
    ws = await make_workspace(session, name="WS-Direct")
    first = await generate_public_id(session, "TC", ws.id)
    second = await generate_public_id(session, "TC", ws.id)
    other_prefix = await generate_public_id(session, "R", ws.id)
    assert first == "TC-1000"
    assert second == "TC-1001"
    assert other_prefix == "R-1000"
