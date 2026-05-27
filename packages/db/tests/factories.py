"""Plain async factory helpers for repository tests.

Polyfactory/factory-boy add a dependency and async-session plumbing we don't need
for M1a — these helpers are simpler: each ``make_*`` builds one persisted row
against the supplied ``AsyncSession`` (flushed, not committed, so the per-test
rollback still isolates everything).

``public_id`` values are generated with ``f"TC-{randint}"`` style placeholders;
the real per-workspace sequences arrive in Task 8.
"""

from __future__ import annotations

import random
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.ids import new_id
from suitest_db.models.audit import AuditLog
from suitest_db.models.case import CaseTag, TestCase
from suitest_db.models.defect import Defect
from suitest_db.models.document import Document
from suitest_db.models.integration import Integration
from suitest_db.models.llm_config import LLMConfig
from suitest_db.models.mcp_provider import McpProvider
from suitest_db.models.project import Project, Suite
from suitest_db.models.requirement import Requirement
from suitest_db.models.run import Run, RunStep
from suitest_db.models.tenancy import Membership
from suitest_db.models.user import User
from suitest_db.models.workspace import Workspace
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_shared.domain.enums import (
    AutonomyLevel,
    CaseSource,
    DefectStatus,
    DocumentKind,
    IntegrationKind,
    McpTransport,
    Role,
    RunStatus,
    RunTrigger,
    Severity,
    StepOutcome,
    Tier,
)


def _pub(prefix: str) -> str:
    return f"{prefix}-{random.randint(10000, 99999)}"


async def make_user(session: AsyncSession, *, name: str = "User") -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"u-{new_id()}@example.com",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
        is_verified=True,
        name=name,
    )
    session.add(user)
    await session.flush()
    return user


async def make_workspace(session: AsyncSession, *, name: str = "WS") -> Workspace:
    ws = Workspace(slug=f"ws-{new_id()}", name=name)
    session.add(ws)
    await session.flush()
    return ws


async def make_membership(
    session: AsyncSession,
    *,
    workspace: Workspace,
    user: User,
    role: Role = Role.QA,
) -> Membership:
    m = Membership(workspace_id=workspace.id, user_id=user.id, role=role)
    session.add(m)
    await session.flush()
    return m


async def make_project(
    session: AsyncSession, *, workspace: Workspace, name: str = "Proj"
) -> Project:
    project = Project(workspace_id=workspace.id, slug=f"p-{new_id()}", name=name)
    session.add(project)
    await session.flush()
    return project


async def make_suite(session: AsyncSession, *, project: Project, name: str = "Suite") -> Suite:
    suite = Suite(project_id=project.id, name=name)
    session.add(suite)
    await session.flush()
    return suite


async def make_test_case(
    session: AsyncSession,
    *,
    suite: Suite,
    name: str = "Case",
    source: CaseSource = CaseSource.MANUAL,
    tags: list[str] | None = None,
) -> TestCase:
    case = TestCase(
        suite_id=suite.id,
        public_id=_pub("TC"),
        name=name,
        source=source,
    )
    session.add(case)
    await session.flush()
    if tags:
        for tag in tags:
            session.add(CaseTag(case_id=case.id, tag=tag))
        await session.flush()
    return case


async def make_requirement(
    session: AsyncSession, *, project: Project, title: str = "Req"
) -> Requirement:
    req = Requirement(project_id=project.id, public_id=_pub("REQ"), title=title)
    session.add(req)
    await session.flush()
    return req


async def make_run(
    session: AsyncSession,
    *,
    project: Project,
    name: str = "Run",
    status: RunStatus = RunStatus.QUEUED,
    branch: str | None = None,
    env: str = "staging",
) -> Run:
    run = Run(
        public_id=_pub("R"),
        project_id=project.id,
        name=name,
        trigger=RunTrigger.MANUAL,
        status=status,
        tier_at_runtime=Tier.ZERO,
        branch=branch,
        env=env,
    )
    session.add(run)
    await session.flush()
    return run


async def make_run_step(
    session: AsyncSession,
    *,
    run: Run,
    case: TestCase,
    step_order: int,
    outcome: StepOutcome,
) -> RunStep:
    rs = RunStep(run_id=run.id, case_id=case.id, step_order=step_order, outcome=outcome)
    session.add(rs)
    await session.flush()
    return rs


async def make_defect(
    session: AsyncSession,
    *,
    workspace: Workspace,
    title: str = "Defect",
    severity: Severity = Severity.HIGH,
    status: DefectStatus = DefectStatus.OPEN,
    component: str | None = None,
) -> Defect:
    defect = Defect(
        public_id=_pub("D"),
        workspace_id=workspace.id,
        title=title,
        severity=severity,
        status=status,
        component=component,
        created_by="tester",
    )
    session.add(defect)
    await session.flush()
    return defect


async def make_audit_log(
    session: AsyncSession,
    *,
    workspace: Workspace,
    action: str,
    resource_id: str,
    resource_type: str = "defect",
) -> AuditLog:
    log = AuditLog(
        workspace_id=workspace.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    session.add(log)
    await session.flush()
    return log


async def make_integration(
    session: AsyncSession,
    *,
    workspace: Workspace,
    kind: IntegrationKind = IntegrationKind.GITHUB,
    name: str = "Integration",
) -> Integration:
    integration = Integration(workspace_id=workspace.id, kind=kind, name=name, config={})
    session.add(integration)
    await session.flush()
    return integration


async def make_document(
    session: AsyncSession,
    *,
    workspace: Workspace,
    kind: DocumentKind = DocumentKind.PRD,
    title: str = "Doc",
) -> Document:
    doc = Document(
        workspace_id=workspace.id,
        kind=kind,
        source="file://doc.md",
        title=title,
        content_hash=new_id(),
    )
    session.add(doc)
    await session.flush()
    return doc


async def make_llm_config(
    session: AsyncSession,
    *,
    workspace: Workspace,
    provider: str = "anthropic",
    model: str = "claude",
    is_active: bool = False,
) -> LLMConfig:
    cfg = LLMConfig(workspace_id=workspace.id, provider=provider, model=model, is_active=is_active)
    session.add(cfg)
    await session.flush()
    return cfg


async def make_mcp_provider(
    session: AsyncSession,
    *,
    workspace: Workspace,
    name: str = "playwright-mcp",
    kind: str = "playwright",
) -> McpProvider:
    provider = McpProvider(
        workspace_id=workspace.id,
        name=name,
        kind=kind,
        endpoint="stdio://playwright",
        transport=McpTransport.STDIO,
    )
    session.add(provider)
    await session.flush()
    return provider


async def make_workspace_capability(
    session: AsyncSession,
    *,
    workspace: Workspace,
    tier: Tier = Tier.ZERO,
    autonomy: AutonomyLevel = AutonomyLevel.MANUAL,
) -> WorkspaceCapability:
    cap = WorkspaceCapability(
        workspace_id=workspace.id, tier=tier, autonomy_level=autonomy, features_json={}
    )
    session.add(cap)
    await session.flush()
    return cap
