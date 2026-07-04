"""Demo seed — Brewly workspace for the 30-second demo (`make demo`).

Creates a self-contained "Demo" workspace whose suite executes against the
live ``demo-app`` compose service. The suite comes from the committed
generation-output fixture ``examples/demo-app/suite.json`` so the demo replays
green at ZERO tier.

Idempotent — safe to re-run on every ``docker compose --profile demo up``.

Env:
    DEMO_SUITE_PATH  path to suite.json  (default: examples/demo-app/suite.json)
    DEMO_APP_URL     base URL substituted for ``${DEMO_APP_URL}``
                     (default: http://demo-app:8089)
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from suitest_shared.domain.enums import (
    AutonomyLevel,
    CaseSource,
    CaseStatus,
    Priority,
    Role,
    TargetKind,
    Tier,
)

from suitest_db.engine import lifespan_engine
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.llm_config import LLMConfig
from suitest_db.models.project import Project, Suite
from suitest_db.models.tenancy import Membership
from suitest_db.models.user import User
from suitest_db.models.workspace import Workspace
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_db.repositories.test_cases import TestCaseCreate, TestCaseRepo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

WORKSPACE_SLUG: Final = "demo"
WORKSPACE_NAME: Final = "Demo"
PROJECT_SLUG: Final = "brewly"
PROJECT_NAME: Final = "Brewly"
DEMO_EMAIL: Final = "demo@suitest.dev"
DEMO_NAME: Final = "Demo"
DEMO_PASSWORD: Final = "demo1234"

_DEFAULT_SUITE_PATH: Final = Path(__file__).parents[4] / "examples" / "demo-app" / "suite.json"

_USER_NS: Final = uuid.UUID("00000000-0000-0000-0000-00000000bbbb")

# No custom McpProvider rows: the fixture routes to the BUNDLED builtins
# (api-http-mcp in-process, playwright-mcp stdio) which the registry seeds for
# every workspace automatically. A custom row with the same name would
# override the builtin and lose its spawn command.


def _load_fixture() -> dict[str, Any]:
    path = Path(os.environ.get("DEMO_SUITE_PATH", str(_DEFAULT_SUITE_PATH)))
    if not path.is_file():
        raise SystemExit(f"demo seed: suite fixture not found at {path}")
    raw = path.read_text()
    demo_app_url = os.environ.get("DEMO_APP_URL", "http://demo-app:8089")
    raw = raw.replace("${DEMO_APP_URL}", demo_app_url)
    data: dict[str, Any] = json.loads(raw)
    return data


class DemoSeeder:
    """Idempotent Brewly demo seeder (same ensure_* pattern as ``seed.Seeder``)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._password_helper = PasswordHelper()
        self._workspace: Workspace | None = None
        self._project: Project | None = None
        self._suite: Suite | None = None

    async def ensure_workspace(self) -> Workspace:
        row = await self.session.scalar(select(Workspace).where(Workspace.slug == WORKSPACE_SLUG))
        if row is None:
            row = Workspace(slug=WORKSPACE_SLUG, name=WORKSPACE_NAME)
            self.session.add(row)
            await self.session.flush()
        self._workspace = row
        return row

    async def ensure_user(self) -> User:
        email_col = User.__table__.c.email
        row = await self.session.scalar(select(User).where(email_col == DEMO_EMAIL))
        if row is None:
            row = User(
                id=uuid.uuid5(_USER_NS, DEMO_EMAIL),
                email=DEMO_EMAIL,
                hashed_password=self._password_helper.hash(DEMO_PASSWORD),
                is_active=True,
                is_superuser=False,
                is_verified=True,
                name=DEMO_NAME,
            )
            self.session.add(row)
            await self.session.flush()
        ws = self._require_workspace()
        membership = await self.session.scalar(
            select(Membership).where(Membership.workspace_id == ws.id, Membership.user_id == row.id)
        )
        if membership is None:
            self.session.add(Membership(workspace_id=ws.id, user_id=row.id, role=Role.OWNER))
            await self.session.flush()
        return row

    async def ensure_project(self) -> Project:
        ws = self._require_workspace()
        row = await self.session.scalar(
            select(Project).where(Project.workspace_id == ws.id, Project.slug == PROJECT_SLUG)
        )
        if row is None:
            row = Project(workspace_id=ws.id, slug=PROJECT_SLUG, name=PROJECT_NAME)
            self.session.add(row)
            await self.session.flush()
        self._project = row
        return row

    async def ensure_suite_from_fixture(self, fixture: dict[str, Any]) -> Suite:
        project = self._require_project()
        ws = self._require_workspace()
        suite_name = str(fixture["suite"])
        suite = await self.session.scalar(
            select(Suite).where(Suite.project_id == project.id, Suite.name == suite_name)
        )
        if suite is None:
            suite = Suite(project_id=project.id, name=suite_name, order=0)
            self.session.add(suite)
            await self.session.flush()
        self._suite = suite

        case_repo = TestCaseRepo(self.session)
        for case_spec in fixture["cases"]:
            existing = await self.session.scalar(
                select(TestCase).where(
                    TestCase.suite_id == suite.id, TestCase.name == case_spec["name"]
                )
            )
            if existing is not None:
                continue
            created = await case_repo.create(
                TestCaseCreate(
                    suite_id=suite.id,
                    name=case_spec["name"],
                    source=CaseSource(case_spec["source"]),
                    status=CaseStatus(case_spec["status"]),
                    priority=Priority(case_spec["priority"]),
                ),
                workspace_id=ws.id,
            )
            created.description = case_spec.get("description")
            for step_spec in case_spec["steps"]:
                self.session.add(
                    TestStep(
                        case_id=created.id,
                        order=int(step_spec["order"]),
                        action=step_spec["action"],
                        expected=step_spec["expected"],
                        code=json.dumps(step_spec["code"]),
                        mcp_provider=case_spec["mcp_provider"],
                        target_kind=TargetKind(case_spec["target_kind"]),
                    )
                )
            await self.session.flush()
        return suite

    async def ensure_capability(self) -> None:
        ws = self._require_workspace()
        if (
            await self.session.scalar(select(LLMConfig).where(LLMConfig.workspace_id == ws.id))
            is None
        ):
            self.session.add(
                LLMConfig(
                    workspace_id=ws.id,
                    provider="none",
                    model="none",
                    config_json={},
                    is_active=False,
                )
            )
        if (
            await self.session.scalar(
                select(WorkspaceCapability).where(WorkspaceCapability.workspace_id == ws.id)
            )
            is None
        ):
            self.session.add(
                WorkspaceCapability(
                    workspace_id=ws.id,
                    tier=Tier.ZERO,
                    autonomy_level=AutonomyLevel.MANUAL,
                    features_json={},
                )
            )
        await self.session.flush()

    async def run_all(self) -> None:
        fixture = _load_fixture()
        await self.ensure_workspace()
        await self.ensure_user()
        await self.ensure_project()
        await self.ensure_suite_from_fixture(fixture)
        await self.ensure_capability()

    def _require_workspace(self) -> Workspace:
        if self._workspace is None:
            raise RuntimeError("ensure_workspace() must run before this step")
        return self._workspace

    def _require_project(self) -> Project:
        if self._project is None:
            raise RuntimeError("ensure_project() must run before this step")
        return self._project


async def _amain() -> None:
    async with (
        lifespan_engine() as (_, session_factory),
        session_factory() as session,
    ):
        seeder = DemoSeeder(session)
        await seeder.run_all()
        await session.commit()


def main() -> None:
    """CLI entrypoint — ``python -m suitest_db.seed_demo``. Idempotent."""
    asyncio.run(_amain())


if __name__ == "__main__":  # pragma: no cover - exercised via the module CLI
    main()
