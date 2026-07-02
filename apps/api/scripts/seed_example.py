"""Seed the DB for the suitest-example dogfood publish.

Creates ONE owner user + ONE workspace + the two projects the example's
``suitest.config.json`` files pin (frontend + backend), all with the EXACT ids
those configs reference so ``publish`` lands without editing the committed
configs. Also mints one API key for the workspace and prints it (shown once) so
it can be dropped into ``suitest-example/.mcp.json`` + used as SUITEST_API_KEY.

Assumes a FRESH schema (run after dropping/recreating + ``alembic upgrade head``).
Idempotent enough to re-run: it upserts by id/slug.

    set -a && . ./.env && set +a
    uv run python apps/api/scripts/seed_example.py
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

from fastapi_users.password import PasswordHelper
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from suitest_api.services.api_key_service import create_api_key
from suitest_db.models.project import Project
from suitest_db.models.tenancy import Membership
from suitest_db.models.user import User
from suitest_db.models.workspace import Workspace
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_shared.domain.enums import AutonomyLevel, Role, Tier

# Owner user for the dogfood workspace.
USER_EMAIL = "dev@suitest.local"
USER_PASSWORD = "devpassword123"
USER_NAME = "Dev"

# Ids pinned by suitest-example/{frontend,backend}/suitest.config.json.
WORKSPACE_ID = "zblb0reubl7cpp9d60uoa274"
WORKSPACE_SLUG = "qa-test"
WORKSPACE_NAME = "QA Test"
PROJECT_FE_ID = "r37knkk7s7xlebxpchho20ht"
PROJECT_BE_ID = "ap333dk4awuq7knta26y3h9v"


async def seed() -> tuple[str, str]:
    url = os.environ.get("SUITEST_DATABASE_URL")
    if not url:
        raise SystemExit("SUITEST_DATABASE_URL is not set (load .env first)")

    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            user = await session.scalar(
                select(User).where(func.lower(User.email) == USER_EMAIL.lower())
            )
            if user is None:
                user = User(
                    id=uuid.uuid4(),
                    email=USER_EMAIL,
                    hashed_password=PasswordHelper().hash(USER_PASSWORD),
                    is_active=True,
                    is_superuser=False,
                    is_verified=True,
                    name=USER_NAME,
                )
                session.add(user)
                await session.flush()

            ws = await session.scalar(select(Workspace).where(Workspace.id == WORKSPACE_ID))
            if ws is None:
                ws = Workspace(id=WORKSPACE_ID, slug=WORKSPACE_SLUG, name=WORKSPACE_NAME)
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
                await session.flush()

            for pid, slug, name in (
                (PROJECT_FE_ID, "qa-test-frontend", "QA Test Frontend"),
                (PROJECT_BE_ID, "qa-test-backend", "QA Test Backend"),
            ):
                existing = await session.scalar(select(Project).where(Project.id == pid))
                if existing is None:
                    session.add(Project(id=pid, workspace_id=ws.id, slug=slug, name=name))
            await session.flush()

            _, token = await create_api_key(
                session,
                workspace_id=ws.id,
                user_id=str(user.id),
                name="mcp-lifecycle",
            )
            await session.commit()
            return ws.id, token
    finally:
        await engine.dispose()


async def _main() -> None:
    ws_id, token = await seed()
    print(
        json.dumps(
            {
                "user": USER_EMAIL,
                "password": USER_PASSWORD,
                "workspace_id": ws_id,
                "project_frontend": PROJECT_FE_ID,
                "project_backend": PROJECT_BE_ID,
                "api_key": token,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(_main())
