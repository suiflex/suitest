"""Seed a deterministic ZERO-tier dogfood state for the real-backend e2e.

State = ONE user + ONE empty workspace (OWNER membership + ZERO capability) and
**nothing else** — no projects, suites, cases, runs, or defects. This is the
real fresh-install state the dogfood loop targets
(``docs/loops/ZERO_READINESS_DOGFOOD_LOOP.md``): with no test data, the user
must be able to create everything from the UI.

Idempotent: re-running reuses the user + workspace and **resets the workspace to
empty** (drops projects, which cascade to suites/cases) so the
"create your first project → suite" journey is always exercisable.

Run against the dev DB the api serves (``SUITEST_DATABASE_URL``):

    uv run python apps/api/scripts/seed_zero_e2e.py
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

from fastapi_users.password import PasswordHelper
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.project import Project, Suite
from suitest_db.models.tenancy import Membership
from suitest_db.models.user import User
from suitest_db.models.workspace import Workspace
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_db.public_id import set_workspace_id
from suitest_shared.domain.enums import AutonomyLevel, CaseSource, Role, TargetKind, Tier

# Public, non-secret e2e fixture credentials (local dogfood DB only). Mirrored in
# apps/web/e2e/realbackend/*.spec.ts.
E2E_EMAIL = "e2e-zero@suitest.local"
E2E_PASSWORD = "dogfood-zero-pw-1"
E2E_WORKSPACE_SLUG = "e2e-zero"
E2E_WORKSPACE_NAME = "E2E Zero"

# A SECOND workspace pre-seeded with a runnable saucedemo case (one
# ``browser_navigate`` step on ``playwright-mcp``) so the run e2e can drive
# "Run now" → PASS through the UI without authoring steps. Kept separate from
# the EMPTY e2e-zero workspace so the bootstrap spec still starts from nothing.
RUN_WORKSPACE_SLUG = "e2e-run"
RUN_WORKSPACE_NAME = "E2E Run"
NAV_CODE = json.dumps(
    {"tool": "browser_navigate", "arguments": {"url": "https://www.saucedemo.com"}}
)
# A deterministically-FAILING step (connection refused on port 1 → the MCP tool
# returns an error → step FAIL → the runner auto-files a defect). Used to lock
# the "make it fail → triage → defect" journey step.
NAV_FAIL_CODE = json.dumps(
    {"tool": "browser_navigate", "arguments": {"url": "http://127.0.0.1:1/"}}
)


async def _seed_run_workspace(session: AsyncSession, *, user: User) -> None:
    """Ensure ``e2e-run`` holds exactly one runnable saucedemo case (idempotent)."""
    ws = await session.scalar(select(Workspace).where(Workspace.slug == RUN_WORKSPACE_SLUG))
    if ws is None:
        ws = Workspace(slug=RUN_WORKSPACE_SLUG, name=RUN_WORKSPACE_NAME)
        session.add(ws)
        await session.flush()
        session.add(Membership(workspace_id=ws.id, user_id=user.id, role=Role.OWNER))
        session.add(
            WorkspaceCapability(
                workspace_id=ws.id,
                tier=Tier.ZERO,
                autonomy_level=AutonomyLevel.MANUAL,
                features_json={},
            )
        )
    else:
        await session.execute(delete(Project).where(Project.workspace_id == ws.id))
    await session.flush()

    project = Project(workspace_id=ws.id, slug="saucedemo", name="SauceDemo")
    session.add(project)
    await session.flush()
    suite = Suite(project_id=project.id, name="Smoke")
    session.add(suite)
    await session.flush()
    case = TestCase(
        workspace_id=ws.id, suite_id=suite.id, name="Open saucedemo", source=CaseSource.MANUAL
    )
    set_workspace_id(case, ws.id)  # public_id before_insert listener needs this
    session.add(case)
    await session.flush()
    session.add(
        TestStep(
            case_id=case.id,
            order=1,
            action="Open saucedemo",
            expected="page loads",
            code=NAV_CODE,
            mcp_provider="playwright-mcp",
            target_kind=TargetKind.FE_WEB,
        )
    )

    # A deterministically-failing case so the run auto-files a defect (journey
    # step 10: make it fail → triage → defect).
    fail_case = TestCase(
        workspace_id=ws.id, suite_id=suite.id, name="Broken checkout", source=CaseSource.MANUAL
    )
    set_workspace_id(fail_case, ws.id)
    session.add(fail_case)
    await session.flush()
    session.add(
        TestStep(
            case_id=fail_case.id,
            order=1,
            action="Open a dead endpoint",
            expected="should fail",
            code=NAV_FAIL_CODE,
            mcp_provider="playwright-mcp",
            target_kind=TargetKind.FE_WEB,
        )
    )


async def seed() -> str:
    """Upsert the user + empty workspace; return the workspace id."""
    url = os.environ.get("SUITEST_DATABASE_URL")
    if not url:
        raise SystemExit("SUITEST_DATABASE_URL is not set (load .env or `make` target)")

    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            # ``func.lower(User.email)`` keeps the comparison a SQL ColumnElement
            # (the fastapi-users ``User.email`` attribute isn't seen as a mapped
            # column by the SQLAlchemy mypy plugin) and is case-insensitive.
            user = await session.scalar(
                select(User).where(func.lower(User.email) == E2E_EMAIL.lower())
            )
            if user is None:
                user = User(
                    id=uuid.uuid4(),
                    email=E2E_EMAIL,
                    hashed_password=PasswordHelper().hash(E2E_PASSWORD),
                    is_active=True,
                    is_superuser=False,
                    is_verified=True,
                    name="E2E Zero",
                )
                session.add(user)
                await session.flush()

            workspace = await session.scalar(
                select(Workspace).where(Workspace.slug == E2E_WORKSPACE_SLUG)
            )
            if workspace is None:
                workspace = Workspace(slug=E2E_WORKSPACE_SLUG, name=E2E_WORKSPACE_NAME)
                session.add(workspace)
                await session.flush()
                session.add(Membership(workspace_id=workspace.id, user_id=user.id, role=Role.OWNER))
                session.add(
                    WorkspaceCapability(
                        workspace_id=workspace.id,
                        tier=Tier.ZERO,
                        autonomy_level=AutonomyLevel.MANUAL,
                        features_json={},
                    )
                )
            else:
                # Reset to empty: drop projects; FK ON DELETE CASCADE removes the
                # workspace's suites + cases so the bootstrap journey is fresh.
                await session.execute(delete(Project).where(Project.workspace_id == workspace.id))
            await _seed_run_workspace(session, user=user)
            await session.commit()
            return workspace.id
    finally:
        await engine.dispose()


async def _main() -> None:
    workspace_id = await seed()
    print(
        f"seeded ZERO dogfood state: user={E2E_EMAIL} password={E2E_PASSWORD} "
        f"workspace={E2E_WORKSPACE_SLUG} id={workspace_id} (no projects/suites/cases)"
    )


if __name__ == "__main__":
    asyncio.run(_main())
