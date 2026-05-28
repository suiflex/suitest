"""Nusantara Retail seed script (docs/DATA_MODEL.md §11, Task 9).

Idempotent, factory-backed seeder. Re-running is safe — every ``ensure_*``
method looks up rows by stable natural key before inserting, so row counts and
contents converge after the first run.

CLI::

    SUITEST_DATABASE_URL=postgresql+asyncpg://... \
    SUITEST_ENCRYPTION_KEY=$(base64 -i ...) \
    uv run python -m suitest_db.seed

The script writes:

* 1 workspace (``nusantara-retail``)
* 3 users (Maya owner, Ari admin, Dimas QA) + 3 memberships, password ``admin123``
* 1 project (``ecommerce-web``), 4 suites
* 18 test cases (mix of ``CaseSource``) with 3-5 steps each
* 5 runs (2 PASS, 2 FAIL, 1 ERROR) with run steps + artifacts on failures
* 3 defects (CRITICAL/HIGH/MEDIUM, OPEN/IN_PROGRESS/RESOLVED)
* 6 requirements (one unlinked → readiness blocker)
* 9 integrations (mix of connected/disconnected with encrypted secrets)
* 2 MCP providers (playwright + api)
* 1 inactive LLMConfig (provider=none, ZERO tier default)
* 1 WorkspaceCapability (ZERO / MANUAL)
* 1 PromptVersion (v1/generate-from-prd 1.0.0)
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from suitest_shared.domain.enums import (
    ArtifactKind,
    AutonomyLevel,
    CaseSource,
    CaseStatus,
    DefectStatus,
    DiagnosisKind,
    IntegrationKind,
    McpTransport,
    Priority,
    Role,
    RunStatus,
    RunTrigger,
    Severity,
    StepOutcome,
    TargetKind,
    Tier,
)

from suitest_db.engine import lifespan_engine
from suitest_db.models.case import CaseTag, TestCase, TestStep
from suitest_db.models.defect import Defect
from suitest_db.models.integration import Integration
from suitest_db.models.llm_config import LLMConfig
from suitest_db.models.mcp_provider import McpProvider
from suitest_db.models.project import Project, Suite
from suitest_db.models.prompt_version import PromptVersion
from suitest_db.models.requirement import Requirement, RequirementLink
from suitest_db.models.run import Artifact, Run, RunStep
from suitest_db.models.tenancy import Membership
from suitest_db.models.user import User
from suitest_db.models.workspace import Workspace
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_db.repositories.defects import DefectCreate, DefectRepo
from suitest_db.repositories.requirements import RequirementCreate, RequirementRepo
from suitest_db.repositories.runs import RunCreate, RunRepo
from suitest_db.repositories.test_cases import TestCaseCreate, TestCaseRepo

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


# --- constants ----------------------------------------------------------------

WORKSPACE_SLUG: Final = "nusantara-retail"
WORKSPACE_NAME: Final = "Nusantara Retail"
PROJECT_SLUG: Final = "ecommerce-web"
PROJECT_NAME: Final = "E-commerce Web"
DEV_PASSWORD: Final = "admin123"

# Suite names + display order (Suite is keyed by name within project).
_SUITE_SPECS: Final[tuple[tuple[str, int], ...]] = (
    ("Auth", 0),
    ("Checkout", 1),
    ("Catalog", 2),
    ("Admin", 3),
)


@dataclass(frozen=True)
class _UserSpec:
    email: str
    name: str
    role: Role


_USER_SPECS: Final[tuple[_UserSpec, ...]] = (
    _UserSpec(email="maya@nusantararetail.local", name="Maya", role=Role.OWNER),
    _UserSpec(email="ari@nusantararetail.local", name="Ari", role=Role.ADMIN),
    _UserSpec(email="dimas@nusantararetail.local", name="Dimas", role=Role.QA),
)


@dataclass(frozen=True)
class _CaseSpec:
    suite: str
    name: str
    source: CaseSource
    priority: Priority
    status: CaseStatus
    target_kind: TargetKind
    mcp_provider: str
    step_count: int  # 3..5


def _mcp_for(target: TargetKind) -> str:
    """Map a step's TargetKind to the MCP provider name (matches Task 9 spec)."""
    if target == TargetKind.FE_WEB:
        return "playwright-mcp"
    if target == TargetKind.BE_REST:
        return "api-mcp"
    if target == TargetKind.DATA:
        return "postgres-mcp"
    if target == TargetKind.BE_GRAPHQL:
        return "graphql-mcp"
    return "playwright-mcp"


# 18 cases: 10 MANUAL, 4 IMPORT, 2 RECORDER, 2 HEURISTIC_CRAWL.
# 1-2 DRAFT (rest ACTIVE), priorities span P0..P3, step counts 3-5.
_CASE_SPECS: Final[tuple[_CaseSpec, ...]] = (
    # --- Auth suite (5) ---
    _CaseSpec(
        "Auth",
        "Login with valid credentials",
        CaseSource.MANUAL,
        Priority.P0,
        CaseStatus.ACTIVE,
        TargetKind.FE_WEB,
        "playwright-mcp",
        4,
    ),
    _CaseSpec(
        "Auth",
        "Login with invalid password",
        CaseSource.MANUAL,
        Priority.P1,
        CaseStatus.ACTIVE,
        TargetKind.FE_WEB,
        "playwright-mcp",
        3,
    ),
    _CaseSpec(
        "Auth",
        "OAuth Google sign-in",
        CaseSource.RECORDER,
        Priority.P1,
        CaseStatus.ACTIVE,
        TargetKind.FE_WEB,
        "playwright-mcp",
        5,
    ),
    _CaseSpec(
        "Auth",
        "Password reset flow",
        CaseSource.MANUAL,
        Priority.P2,
        CaseStatus.ACTIVE,
        TargetKind.FE_WEB,
        "playwright-mcp",
        4,
    ),
    _CaseSpec(
        "Auth",
        "Token refresh endpoint",
        CaseSource.IMPORT,
        Priority.P1,
        CaseStatus.ACTIVE,
        TargetKind.BE_REST,
        "api-mcp",
        3,
    ),
    # --- Checkout suite (5) ---
    _CaseSpec(
        "Checkout",
        "Add item to cart",
        CaseSource.MANUAL,
        Priority.P0,
        CaseStatus.ACTIVE,
        TargetKind.FE_WEB,
        "playwright-mcp",
        4,
    ),
    _CaseSpec(
        "Checkout",
        "Apply discount voucher",
        CaseSource.MANUAL,
        Priority.P1,
        CaseStatus.ACTIVE,
        TargetKind.FE_WEB,
        "playwright-mcp",
        5,
    ),
    _CaseSpec(
        "Checkout",
        "Complete payment with credit card",
        CaseSource.MANUAL,
        Priority.P0,
        CaseStatus.ACTIVE,
        TargetKind.FE_WEB,
        "playwright-mcp",
        5,
    ),
    _CaseSpec(
        "Checkout",
        "Order confirmation API",
        CaseSource.IMPORT,
        Priority.P1,
        CaseStatus.ACTIVE,
        TargetKind.BE_REST,
        "api-mcp",
        3,
    ),
    _CaseSpec(
        "Checkout",
        "Tax calculation edge cases",
        CaseSource.HEURISTIC_CRAWL,
        Priority.P2,
        CaseStatus.DRAFT,
        TargetKind.BE_REST,
        "api-mcp",
        4,
    ),
    # --- Catalog suite (4) ---
    _CaseSpec(
        "Catalog",
        "Search product by keyword",
        CaseSource.MANUAL,
        Priority.P1,
        CaseStatus.ACTIVE,
        TargetKind.FE_WEB,
        "playwright-mcp",
        3,
    ),
    _CaseSpec(
        "Catalog",
        "Filter by category",
        CaseSource.MANUAL,
        Priority.P2,
        CaseStatus.ACTIVE,
        TargetKind.FE_WEB,
        "playwright-mcp",
        3,
    ),
    _CaseSpec(
        "Catalog",
        "Product detail page renders",
        CaseSource.RECORDER,
        Priority.P1,
        CaseStatus.ACTIVE,
        TargetKind.FE_WEB,
        "playwright-mcp",
        4,
    ),
    _CaseSpec(
        "Catalog",
        "Inventory API stock check",
        CaseSource.IMPORT,
        Priority.P2,
        CaseStatus.ACTIVE,
        TargetKind.BE_REST,
        "api-mcp",
        3,
    ),
    # --- Admin suite (4) ---
    _CaseSpec(
        "Admin",
        "Bulk import products CSV",
        CaseSource.MANUAL,
        Priority.P2,
        CaseStatus.ACTIVE,
        TargetKind.FE_WEB,
        "playwright-mcp",
        5,
    ),
    _CaseSpec(
        "Admin",
        "Manage user roles",
        CaseSource.MANUAL,
        Priority.P1,
        CaseStatus.ACTIVE,
        TargetKind.FE_WEB,
        "playwright-mcp",
        4,
    ),
    _CaseSpec(
        "Admin",
        "Audit log export",
        CaseSource.IMPORT,
        Priority.P3,
        CaseStatus.DRAFT,
        TargetKind.BE_REST,
        "api-mcp",
        3,
    ),
    _CaseSpec(
        "Admin",
        "Dashboard widget heatmap",
        CaseSource.HEURISTIC_CRAWL,
        Priority.P3,
        CaseStatus.ACTIVE,
        TargetKind.FE_WEB,
        "playwright-mcp",
        3,
    ),
)


@dataclass(frozen=True)
class _RunSpec:
    name: str
    branch: str
    status: RunStatus
    fail_step_index: int | None  # None=all pass, otherwise (0-indexed) FAIL/ERROR there
    error_run: bool  # if True, the failing step is ERROR not FAIL


_RUN_SPECS: Final[tuple[_RunSpec, ...]] = (
    _RunSpec("CI #2041 main", "main", RunStatus.PASS, None, False),
    _RunSpec("CI #2042 main", "main", RunStatus.PASS, None, False),
    _RunSpec("CI #2043 release-1.4", "release-1.4", RunStatus.FAIL, 2, False),
    _RunSpec("CI #2044 release-1.4", "release-1.4", RunStatus.FAIL, 1, False),
    _RunSpec("CI #2045 main", "main", RunStatus.ERROR, 0, True),
)


@dataclass(frozen=True)
class _IntegrationSpec:
    kind: IntegrationKind
    name: str
    status: str  # "active" or "disconnected"
    secret: str | None  # plaintext PAT/token (encrypted on write); None for disconnected


_INTEGRATION_SPECS: Final[tuple[_IntegrationSpec, ...]] = (
    _IntegrationSpec(
        IntegrationKind.GITHUB, "GitHub (nusantara-retail)", "active", "ghp_seed_pat_001"
    ),
    _IntegrationSpec(
        IntegrationKind.JIRA, "Jira (Nusantara Retail)", "active", "jira-token-seed-001"
    ),
    _IntegrationSpec(IntegrationKind.SLACK, "Slack (#qa-alerts)", "disconnected", None),
    _IntegrationSpec(IntegrationKind.LINEAR, "Linear (product)", "disconnected", None),
    _IntegrationSpec(IntegrationKind.JENKINS, "Jenkins (internal CI)", "disconnected", None),
    _IntegrationSpec(
        IntegrationKind.MCP_BROWSER_USE, "Browser-Use MCP (staging)", "disconnected", None
    ),
    _IntegrationSpec(
        IntegrationKind.MCP_PLAYWRIGHT, "Playwright MCP (bundled)", "active", "mcp-playwright-key"
    ),
    _IntegrationSpec(IntegrationKind.MCP_API, "API MCP (bundled)", "active", "mcp-api-key"),
    _IntegrationSpec(IntegrationKind.MCP_POSTGRES, "Postgres MCP (staging)", "disconnected", None),
)


@dataclass(frozen=True)
class _DefectSpec:
    title: str
    severity: Severity
    status: DefectStatus
    case_name: str  # match _CaseSpec.name
    run_name: str  # match _RunSpec.name
    component: str
    description: str


_DEFECT_SPECS: Final[tuple[_DefectSpec, ...]] = (
    _DefectSpec(
        title="Checkout payment returns 500 on rounded total",
        severity=Severity.CRITICAL,
        status=DefectStatus.OPEN,
        case_name="Complete payment with credit card",
        run_name="CI #2043 release-1.4",
        component="checkout",
        description="Rounding tax breaks payment provider call.",
    ),
    _DefectSpec(
        title="Voucher discount sometimes applied twice",
        severity=Severity.HIGH,
        status=DefectStatus.IN_PROGRESS,
        case_name="Apply discount voucher",
        run_name="CI #2044 release-1.4",
        component="checkout",
        description="Idempotency key drift between cart + payment.",
    ),
    _DefectSpec(
        title="Login button flicker on slow networks",
        severity=Severity.MEDIUM,
        status=DefectStatus.RESOLVED,
        case_name="Login with valid credentials",
        run_name="CI #2045 main",
        component="auth",
        description="CSS race between react-hydrate and feature flag fetch.",
    ),
)


@dataclass(frozen=True)
class _RequirementSpec:
    title: str
    description: str
    linked_cases: tuple[str, ...]  # subset of _CASE_SPECS.name; empty → unlinked blocker


_REQUIREMENT_SPECS: Final[tuple[_RequirementSpec, ...]] = (
    _RequirementSpec(
        title="User can sign in with email + password",
        description="Primary login flow accessible to all customer roles.",
        linked_cases=("Login with valid credentials", "Login with invalid password"),
    ),
    _RequirementSpec(
        title="User can complete a paid checkout",
        description="Cart → payment → confirmation happy path.",
        linked_cases=(
            "Add item to cart",
            "Complete payment with credit card",
            "Order confirmation API",
        ),
    ),
    _RequirementSpec(
        title="Catalog search returns relevant products",
        description="Search service ranks active SKUs first.",
        linked_cases=("Search product by keyword", "Filter by category"),
    ),
    _RequirementSpec(
        title="Admin can manage user roles",
        description="RBAC management for OWNER/ADMIN/QA/VIEWER.",
        linked_cases=("Manage user roles",),
    ),
    _RequirementSpec(
        title="Admin can audit data export",
        description="Audit log exporter writes signed CSV.",
        linked_cases=("Audit log export",),
    ),
    # Intentionally unlinked → readiness blocker fixture.
    _RequirementSpec(
        title="Mobile parity for catalog browsing",
        description="Out of scope for v1 — tracked for readiness blocker test.",
        linked_cases=(),
    ),
)


_MCP_PROVIDERS: Final[tuple[tuple[str, str, str, TargetKind], ...]] = (
    ("playwright-mcp", "playwright", "stdio://playwright", TargetKind.FE_WEB),
    ("api-mcp", "api", "stdio://api-http", TargetKind.BE_REST),
)


# Deterministic user UUIDs so re-runs converge (UUID5 over a fixed namespace).
_USER_NS: Final = uuid.UUID("00000000-0000-0000-0000-00000000aaaa")


def _user_uuid(email: str) -> uuid.UUID:
    return uuid.uuid5(_USER_NS, email)


_PROMPT_NAME: Final = "v1/generate-from-prd"
_PROMPT_VERSION: Final = "1.0.0"
_PROMPT_CONTENT: Final = (
    "You are Suitest's PRD-to-test-case generator. "
    "Given a product requirements document, produce one TestCase JSON per acceptance criterion."
)


def _prompt_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# --- seeder -------------------------------------------------------------------


class Seeder:
    """Idempotent Nusantara Retail seeder wrapping one ``AsyncSession``.

    All ``ensure_*`` methods are safe to call repeatedly — they look up rows by
    a stable natural key (slug, email, ``(workspace_id, name)``…) before
    inserting. Callers commit the session themselves (the CLI entrypoint does).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._password_helper = PasswordHelper()
        # Caches populated by ensure_* methods so later steps can refer back
        # without re-querying. Populated lazily.
        self._workspace: Workspace | None = None
        self._users: dict[str, User] = {}
        self._project: Project | None = None
        self._suites: dict[str, Suite] = {}
        self._cases: dict[str, TestCase] = {}
        self._runs: dict[str, Run] = {}

    # --- workspace / users / membership ---------------------------------------

    async def ensure_workspace(self) -> Workspace:
        row = await self.session.scalar(select(Workspace).where(Workspace.slug == WORKSPACE_SLUG))
        if row is None:
            row = Workspace(slug=WORKSPACE_SLUG, name=WORKSPACE_NAME)
            self.session.add(row)
            await self.session.flush()
        self._workspace = row
        return row

    async def ensure_users(self) -> dict[str, User]:
        """Insert Maya / Ari / Dimas (idempotent by email).

        Password hashed via FastAPI-Users' ``PasswordHelper`` so the dev login
        flow accepts ``DEV_PASSWORD`` for every seeded user.
        """
        hashed = self._password_helper.hash(DEV_PASSWORD)
        # ``User.email`` is declared as a plain ``str`` under ``TYPE_CHECKING`` by
        # the FastAPI-Users base (real Mapped column at runtime), so mypy needs
        # the table-column access path to recognise the ``==`` overload.
        email_col = User.__table__.c.email
        for spec in _USER_SPECS:
            row = await self.session.scalar(select(User).where(email_col == spec.email))
            if row is None:
                row = User(
                    id=_user_uuid(spec.email),
                    email=spec.email,
                    hashed_password=hashed,
                    is_active=True,
                    is_superuser=False,
                    is_verified=True,
                    name=spec.name,
                )
                self.session.add(row)
                await self.session.flush()
            self._users[spec.email] = row
        return self._users

    async def ensure_memberships(self) -> None:
        ws = self._require_workspace()
        for spec in _USER_SPECS:
            user = self._users[spec.email]
            existing = await self.session.scalar(
                select(Membership).where(
                    Membership.workspace_id == ws.id,
                    Membership.user_id == user.id,
                )
            )
            if existing is None:
                self.session.add(Membership(workspace_id=ws.id, user_id=user.id, role=spec.role))
        await self.session.flush()

    # --- project / suites -----------------------------------------------------

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

    async def ensure_suites(self) -> dict[str, Suite]:
        project = self._require_project()
        for name, order in _SUITE_SPECS:
            existing = await self.session.scalar(
                select(Suite).where(Suite.project_id == project.id, Suite.name == name)
            )
            if existing is None:
                existing = Suite(project_id=project.id, name=name, order=order)
                self.session.add(existing)
                await self.session.flush()
            self._suites[name] = existing
        return self._suites

    # --- test cases ------------------------------------------------------------

    async def ensure_test_cases(self) -> dict[str, TestCase]:
        ws = self._require_workspace()
        case_repo = TestCaseRepo(self.session)
        for spec in _CASE_SPECS:
            suite = self._suites[spec.suite]
            existing = await self.session.scalar(
                select(TestCase).where(TestCase.suite_id == suite.id, TestCase.name == spec.name)
            )
            if existing is None:
                existing = await case_repo.create(
                    TestCaseCreate(
                        suite_id=suite.id,
                        name=spec.name,
                        source=spec.source,
                        status=spec.status,
                        priority=spec.priority,
                    ),
                    workspace_id=ws.id,
                )
                # Steps + a single tag matching the suite.
                for order_idx in range(spec.step_count):
                    step = TestStep(
                        case_id=existing.id,
                        order=order_idx,
                        action=f"Step {order_idx + 1} for {spec.name}",
                        expected=f"Outcome {order_idx + 1} observed",
                        code=(
                            f"// {spec.mcp_provider} step {order_idx + 1}\n"
                            f"await mcp.call('act', {{ id: '{order_idx + 1}' }});"
                        ),
                        mcp_provider=spec.mcp_provider,
                        target_kind=spec.target_kind,
                    )
                    self.session.add(step)
                self.session.add(CaseTag(case_id=existing.id, tag=spec.suite.lower()))
                await self.session.flush()
            self._cases[spec.name] = existing
        return self._cases

    # --- runs / steps / artifacts ---------------------------------------------

    async def ensure_runs(self) -> dict[str, Run]:
        """Insert 5 runs with per-step outcomes + artifacts on failures.

        The set of cases attached to each run is deterministic — the first 5
        cases (across all suites) seed each run's step list so failures land on
        meaningful targets and the test reporter can lookup `case_public_id` /
        `run_public_id` consistently.
        """
        ws = self._require_workspace()
        project = self._require_project()
        run_repo = RunRepo(self.session)

        # Pick a deterministic ordered slice of cases for run-step generation.
        case_pool: list[TestCase] = [self._cases[s.name] for s in _CASE_SPECS]

        for spec in _RUN_SPECS:
            existing = await self.session.scalar(
                select(Run).where(Run.project_id == project.id, Run.name == spec.name)
            )
            if existing is None:
                existing = await run_repo.create(
                    RunCreate(
                        project_id=project.id,
                        name=spec.name,
                        trigger=RunTrigger.CI_PUSH,
                        tier_at_runtime=Tier.ZERO,
                        branch=spec.branch,
                        status=spec.status,
                    ),
                    workspace_id=ws.id,
                )
                # 5 steps per run, one per case in the pool[:5].
                pass_count = 0
                fail_count = 0
                for step_order, case in enumerate(case_pool[:5]):
                    if spec.fail_step_index is not None and step_order == spec.fail_step_index:
                        outcome = StepOutcome.ERROR if spec.error_run else StepOutcome.FAIL
                    else:
                        outcome = StepOutcome.PASS
                    rs = RunStep(
                        run_id=existing.id,
                        case_id=case.id,
                        step_order=step_order,
                        outcome=outcome,
                        stdout=None,
                        stderr=(
                            f"step {step_order} {outcome.value}"
                            if outcome != StepOutcome.PASS
                            else None
                        ),
                        error_message=(
                            f"{outcome.value}: assertion failed at step {step_order}"
                            if outcome != StepOutcome.PASS
                            else None
                        ),
                    )
                    self.session.add(rs)
                    await self.session.flush()
                    if outcome == StepOutcome.PASS:
                        pass_count += 1
                    else:
                        fail_count += 1
                        # One screenshot artifact per failed step.
                        self.session.add(
                            Artifact(
                                run_step_id=rs.id,
                                kind=ArtifactKind.SCREENSHOT,
                                url=(
                                    f"s3://suitest-artifacts/seed/"
                                    f"{existing.public_id}/step-{step_order}.png"
                                ),
                                size_bytes=128_000,
                                mime_type="image/png",
                            )
                        )
                existing.total_steps = pass_count + fail_count
                existing.passed_steps = pass_count
                existing.failed_steps = fail_count
                await self.session.flush()
            self._runs[spec.name] = existing
        return self._runs

    # --- defects ---------------------------------------------------------------

    async def ensure_defects(self) -> list[Defect]:
        ws = self._require_workspace()
        defect_repo = DefectRepo(self.session)
        out: list[Defect] = []
        for spec in _DEFECT_SPECS:
            existing = await self.session.scalar(
                select(Defect).where(Defect.workspace_id == ws.id, Defect.title == spec.title)
            )
            if existing is None:
                case = self._cases[spec.case_name]
                run = self._runs[spec.run_name]
                existing = await defect_repo.create(
                    DefectCreate(
                        workspace_id=ws.id,
                        title=spec.title,
                        severity=spec.severity,
                        status=spec.status,
                        component=spec.component,
                        created_by="seed-script",
                        test_case_id=case.id,
                        run_id=run.id,
                        agent_diagnosis_kind=DiagnosisKind.MANUAL_TRIAGE,
                        description=spec.description,
                    )
                )
            out.append(existing)
        return out

    # --- requirements + links -------------------------------------------------

    async def ensure_requirements(self) -> list[Requirement]:
        ws = self._require_workspace()
        project = self._require_project()
        req_repo = RequirementRepo(self.session)
        out: list[Requirement] = []
        for spec in _REQUIREMENT_SPECS:
            existing = await self.session.scalar(
                select(Requirement).where(
                    Requirement.project_id == project.id, Requirement.title == spec.title
                )
            )
            if existing is None:
                existing = await req_repo.create(
                    RequirementCreate(
                        project_id=project.id,
                        title=spec.title,
                        description=spec.description,
                    ),
                    workspace_id=ws.id,
                )
                for case_name in spec.linked_cases:
                    case = self._cases[case_name]
                    self.session.add(RequirementLink(requirement_id=existing.id, case_id=case.id))
                await self.session.flush()
            out.append(existing)
        return out

    # --- integrations ---------------------------------------------------------

    async def ensure_integrations(self) -> list[Integration]:
        ws = self._require_workspace()
        out: list[Integration] = []
        for spec in _INTEGRATION_SPECS:
            existing = await self.session.scalar(
                select(Integration).where(
                    Integration.workspace_id == ws.id,
                    Integration.kind == spec.kind,
                    Integration.name == spec.name,
                )
            )
            if existing is None:
                existing = Integration(
                    workspace_id=ws.id,
                    kind=spec.kind,
                    name=spec.name,
                    config={"seeded": True},
                    secrets_encrypted=spec.secret,  # EncryptedBytes encrypts on bind
                    status=spec.status,
                )
                self.session.add(existing)
                await self.session.flush()
            out.append(existing)
        return out

    # --- MCP providers --------------------------------------------------------

    async def ensure_mcp_providers(self) -> list[McpProvider]:
        ws = self._require_workspace()
        out: list[McpProvider] = []
        for name, kind, endpoint, default_target in _MCP_PROVIDERS:
            existing = await self.session.scalar(
                select(McpProvider).where(
                    McpProvider.workspace_id == ws.id, McpProvider.name == name
                )
            )
            if existing is None:
                existing = McpProvider(
                    workspace_id=ws.id,
                    name=name,
                    kind=kind,
                    endpoint=endpoint,
                    transport=McpTransport.STDIO,
                    config_json={},
                    is_default_for_target={default_target.value: True},
                    health_status="unknown",
                )
                self.session.add(existing)
                await self.session.flush()
            out.append(existing)
        return out

    # --- llm config / capability / prompt -------------------------------------

    async def ensure_llm_config(self) -> LLMConfig:
        ws = self._require_workspace()
        existing = await self.session.scalar(
            select(LLMConfig).where(LLMConfig.workspace_id == ws.id)
        )
        if existing is None:
            existing = LLMConfig(
                workspace_id=ws.id,
                provider="none",
                model="none",
                config_json={},
                is_active=False,
            )
            self.session.add(existing)
            await self.session.flush()
        return existing

    async def ensure_workspace_capability(self) -> WorkspaceCapability:
        ws = self._require_workspace()
        existing = await self.session.scalar(
            select(WorkspaceCapability).where(WorkspaceCapability.workspace_id == ws.id)
        )
        if existing is None:
            existing = WorkspaceCapability(
                workspace_id=ws.id,
                tier=Tier.ZERO,
                autonomy_level=AutonomyLevel.MANUAL,
                features_json={},
            )
            self.session.add(existing)
            await self.session.flush()
        return existing

    async def ensure_prompt_version(self) -> PromptVersion:
        existing = await self.session.scalar(
            select(PromptVersion).where(
                PromptVersion.name == _PROMPT_NAME, PromptVersion.version == _PROMPT_VERSION
            )
        )
        if existing is None:
            existing = PromptVersion(
                name=_PROMPT_NAME,
                version=_PROMPT_VERSION,
                content=_PROMPT_CONTENT,
                hash=_prompt_hash(_PROMPT_CONTENT),
            )
            self.session.add(existing)
            await self.session.flush()
        return existing

    # --- orchestration --------------------------------------------------------

    async def run_all(self) -> None:
        """Execute every ``ensure_*`` step in dependency order."""
        await self.ensure_workspace()
        await self.ensure_users()
        await self.ensure_memberships()
        await self.ensure_project()
        await self.ensure_suites()
        await self.ensure_test_cases()
        await self.ensure_runs()
        await self.ensure_defects()
        await self.ensure_requirements()
        await self.ensure_integrations()
        await self.ensure_mcp_providers()
        await self.ensure_llm_config()
        await self.ensure_workspace_capability()
        await self.ensure_prompt_version()

    # --- internals ------------------------------------------------------------

    def _require_workspace(self) -> Workspace:
        if self._workspace is None:
            raise RuntimeError("ensure_workspace() must run before this step")
        return self._workspace

    def _require_project(self) -> Project:
        if self._project is None:
            raise RuntimeError("ensure_project() must run before this step")
        return self._project


# --- CLI ----------------------------------------------------------------------


async def _amain() -> None:
    async with (
        lifespan_engine() as (_, session_factory),
        session_factory() as session,
    ):
        seeder = Seeder(session)
        await seeder.run_all()
        await session.commit()


def main() -> None:
    """CLI entrypoint — ``python -m suitest_db.seed``.

    Reads ``SUITEST_DATABASE_URL`` (via :class:`DbSettings`), opens an async
    session, runs the seeder, and commits. Idempotent — safe to re-run.
    """
    asyncio.run(_amain())


__all__: Sequence[str] = ("DEV_PASSWORD", "Seeder", "main")


if __name__ == "__main__":  # pragma: no cover - exercised via the module CLI
    main()
