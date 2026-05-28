"""End-to-end seed smoke test (Task 9 §9.6).

Runs the Nusantara Retail seeder against a fresh testcontainer DB, then drives
the read API with Maya impersonated via the existing ``api_db`` override
pattern. Asserts that listing every seeded suite returns exactly 18 cases
in total — i.e. the seeder produced the M0-7 acceptance shape end-to-end.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from suitest_db.models.project import Project, Suite
from suitest_db.models.user import User
from suitest_db.models.workspace import Workspace
from suitest_db.seed import PROJECT_SLUG, WORKSPACE_SLUG, Seeder

if TYPE_CHECKING:
    from api_harness import ApiDb


@pytest.mark.asyncio
async def test_seed_lists_eighteen_cases_via_api(api_db: ApiDb) -> None:
    """Seeder → list each suite via /test-cases as Maya → total == 18 cases."""
    # Seed against the testcontainer DB.
    async with api_db.maker() as session:
        await Seeder(session).run_all()
        await session.commit()

    # Look up Maya + the seeded workspace + project + suites for the API calls.
    async with api_db.maker() as session:
        ws = await session.scalar(select(Workspace).where(Workspace.slug == WORKSPACE_SLUG))
        assert ws is not None
        project = await session.scalar(
            select(Project).where(Project.workspace_id == ws.id, Project.slug == PROJECT_SLUG)
        )
        assert project is not None
        suite_rows = list(
            (await session.scalars(select(Suite).where(Suite.project_id == project.id))).all()
        )
        email_col = User.__table__.c.email
        maya = await session.scalar(select(User).where(email_col == "maya@nusantararetail.local"))
        assert maya is not None
        # Detach from this session so the override (which opens its own session)
        # doesn't re-attach a closed instance.
        suite_ids = [s.id for s in suite_rows]
        ws_id = ws.id
        maya_user = maya

    # Drive the API as Maya. Endpoint requires a suiteId, so we aggregate across
    # the four seeded suites; the sum must equal the seeded 18 cases.
    total = 0
    async with api_db.client(maya_user) as c:
        for sid in suite_ids:
            resp = await c.get(
                f"/api/v1/test-cases?suiteId={sid}&limit=100",
                headers={"X-Workspace-Id": ws_id},
            )
            assert resp.status_code == 200, resp.text
            total += len(resp.json()["items"])
    assert total == 18
