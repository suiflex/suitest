"""public_id uniqueness must be PER-WORKSPACE, not global (dogfood blocker #3).

``generate_public_id`` mints per-workspace ``TC-N`` sequences (each workspace
restarts at 1), but ``test_cases.public_id`` was declared ``unique=True``
(GLOBAL), so the first case in any second workspace collided with the first
workspace's ``TC-1`` → ``POST /test-cases`` 500. The fix is a composite unique
``(workspace_id, public_id)`` so two workspaces can each own a ``TC-1``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.project import Project, Suite
from suitest_db.models.workspace import Workspace
from suitest_db.repositories.test_cases import TestCaseCreate, TestCaseRepo
from suitest_shared.domain.enums import CaseSource

if TYPE_CHECKING:
    from api_harness import ApiDb


@pytest.mark.asyncio
async def test_first_case_in_two_workspaces_does_not_collide(api_db: ApiDb) -> None:
    async with api_db.maker() as session:
        ws_a = Workspace(slug="pid-ws-a", name="A")
        ws_b = Workspace(slug="pid-ws-b", name="B")
        session.add_all([ws_a, ws_b])
        await session.flush()

        proj_a = Project(workspace_id=ws_a.id, slug="p", name="P")
        proj_b = Project(workspace_id=ws_b.id, slug="p", name="P")
        session.add_all([proj_a, proj_b])
        await session.flush()

        suite_a = Suite(project_id=proj_a.id, name="S")
        suite_b = Suite(project_id=proj_b.id, name="S")
        session.add_all([suite_a, suite_b])
        await session.flush()

        repo = TestCaseRepo(session)
        case_a = await repo.create(
            TestCaseCreate(suite_id=suite_a.id, name="a", source=CaseSource.MANUAL),
            workspace_id=ws_a.id,
        )
        # Before the fix this raised IntegrityError (global unique on public_id).
        case_b = await repo.create(
            TestCaseCreate(suite_id=suite_b.id, name="b", source=CaseSource.MANUAL),
            workspace_id=ws_b.id,
        )
        await session.commit()

    # Each workspace owns an independent TC sequence (starts at 1000), so both
    # the first cases share the same per-workspace public id yet coexist — the
    # composite (workspace_id, public_id) unique lets them, where the old global
    # unique 500'd.
    assert case_a.public_id == "TC-1000"
    assert case_b.public_id == "TC-1000"
    assert case_a.workspace_id == ws_a.id
    assert case_b.workspace_id == ws_b.id
