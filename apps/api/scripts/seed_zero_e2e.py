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
import os
import uuid

from fastapi_users.password import PasswordHelper
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from suitest_db.models.project import Project
from suitest_db.models.tenancy import Membership
from suitest_db.models.user import User
from suitest_db.models.workspace import Workspace
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_shared.domain.enums import AutonomyLevel, Role, Tier

# Public, non-secret e2e fixture credentials (local dogfood DB only). Mirrored in
# apps/web/e2e-realbackend/bootstrap.spec.ts.
E2E_EMAIL = "e2e-zero@suitest.local"
E2E_PASSWORD = "dogfood-zero-pw-1"
E2E_WORKSPACE_SLUG = "e2e-zero"
E2E_WORKSPACE_NAME = "E2E Zero"


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
