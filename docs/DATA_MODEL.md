# docs/DATA_MODEL.md

> SQLAlchemy 2.0 (async) schema + Pydantic v2 domain models untuk Suitest OSS. **Source of truth** — kalau menambah/mengubah model, update doc ini dalam PR yang sama.

> ℹ️ **Built today:** schema through Alembic migration `0028` (M1e), incl. `run_step_logs` and `oauth_accounts` (FastAPI-Users). **Not built (M3–M4 spec):** `llm_config`, `agent_sessions`, eval tables, `webhook_dispatch_attempts`. Verify against `packages/db/alembic/versions/`.
>
> Stack: Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 (async) · Alembic · Postgres 16 + `pgvector`. **Postgres-only.** Tidak ada dukungan SQLite/MySQL/Mongo di OSS v1.0.
>
> Cross-links: [API.md](./API.md) · [ARCHITECTURE.md](./ARCHITECTURE.md) · [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md) · [MCP_PLUGINS.md](./MCP_PLUGINS.md) · [AUTONOMY.md](./AUTONOMY.md) · [GENERATORS.md](./GENERATORS.md) · [pivot design memo](./superpowers/specs/2026-05-26-suitest-oss-pivot-design.md).

---

## 1. ER diagram

```
Workspace ──< User (via Membership)
   │
   ├──< Project ──< Suite ──< TestCase ──< TestStep (mcp_provider, target_kind)
   │                              │           └──< Artifact (via RunStep)
   │                              │
   │                              ├──< CaseTag
   │                              ├──< RequirementLink ──> Requirement
   │                              └──< CodeExport (Playwright/Cypress/Selenium)
   │
   ├──< Run (tier_at_runtime) ──< RunStep ──< Artifact
   │
   ├──< Defect (agent_diagnosis_kind) ──> TestCase
   │       └──> ExternalIssue (Jira/Linear/GitHub)
   │
   ├──< Integration  ◄── (kind expanded: MCP_API, MCP_POSTGRES, MCP_K8S, …)
   │
   ├──< McpProvider (registry, per-workspace, default-routing)
   │
   ├──< LLMConfig (workspace-scoped, AES-GCM key)
   │
   ├──< Invitation (invite-only onboarding, token hash)
   │
   ├──< WorkspaceCapability (materialized tier + autonomy snapshot)
   │
   ├──< AgentSession (prompt_version, seed, temperature, cost_usd, provider)
   │       └──< AgentMessage ──< AgentToolCall (mcp_provider)
   │
   ├──< PromptVersion (referenced by AgentSession)
   │
   ├──< GeneratorRun (deterministic generators: openapi/recorder/heuristic/…)
   │
   ├──< EvalRun (v1.x eval harness — schema present v1.0)
   │
   ├──< Document (PRD, OpenAPI, URL crawl, …)
   │       └──< DocumentChunk (pgvector embedding, variable dim)
   │
   └──< AuditLog

User ──< PasswordResetRequest (pre-SMTP reset link review)
```

---

## 2. Pydantic v2 domain models

> Domain models hidup di `packages/shared/domain/` dan dipakai oleh service layer + serialisasi API. Bersifat **DB-agnostic**: tidak meng-import SQLAlchemy. Mapping ORM ↔ domain dilakukan oleh service / repository.
>
> Konvensi:
> - `BaseModel` dgn `model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True, populate_by_name=True)` agar bisa dibangun dari ORM rows.
> - Field IDs di-tag `Annotated[str, Field(min_length=1)]`.
> - Datetimes always UTC (`datetime`).
> - Enums di `packages/shared/domain/enums.py` (lihat §6).

```python
# packages/shared/domain/base.py
from __future__ import annotations
from datetime import datetime
from typing import Annotated, Any
from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
        populate_by_name=True,
        use_enum_values=False,
    )
```

### 2.1 Tenancy & identity

```python
# packages/shared/domain/workspace.py
import uuid
from .base import DomainModel
from .enums import Role, Tier, AutonomyLevel


class Workspace(DomainModel):
    id: str
    slug: str
    name: str
    region: str = "ap-southeast-1"
    created_at: datetime
    updated_at: datetime


class User(DomainModel):
    id: str
    email: str
    name: str
    avatar_url: str | None = None
    must_change_password: bool = False
    created_at: datetime


class Membership(DomainModel):
    id: str
    workspace_id: str
    user_id: uuid.UUID
    role: Role = Role.QA
    created_at: datetime


class Invitation(DomainModel):
    id: str
    workspace_id: str
    email: str
    role: Role
    expires_at: datetime
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class PasswordResetRequest(DomainModel):
    id: str
    email: str
    expires_at: datetime
    used_at: datetime | None = None
    created_at: datetime
```

### 2.2 Projects, suites, cases, steps (with computed `executable`)

```python
# packages/shared/domain/case.py
import uuid
from .base import DomainModel
from .enums import (
    CaseSource, CaseStatus, Priority, TargetKind, Tier,
)


class TestStep(DomainModel):
    id: str
    case_id: str
    order: int
    action: str
    expected: str
    code: str | None = None
    data: dict[str, Any] | None = None
    mcp_provider: str = "playwright-mcp"       # NEW
    target_kind: TargetKind = TargetKind.FE_WEB # NEW

    def executable(self, tier: Tier) -> bool:
        """
        Computed: a step is executable iff:
          - it has explicit `code` (deterministic), OR
          - the workspace has LLM tier (LOCAL/CLOUD) and an `action` (agentic translate).
        """
        if self.code:
            return True
        return tier in (Tier.LOCAL, Tier.CLOUD) and bool(self.action)


class TestCase(DomainModel):
    id: str
    suite_id: str
    public_id: str
    name: str
    description: str | None = None
    preconditions: str | None = None
    source: CaseSource
    status: CaseStatus = CaseStatus.ACTIVE
    priority: Priority = Priority.P2
    owner_id: uuid.UUID | None = None
    generated_by: str | None = None
    generated_from: dict[str, Any] | None = None
    estimated_ms: int | None = None
    # Phase 2 (lifecycle ingest): automation linkage + denormalized last-run.
    automation_file_path: str | None = None
    automation_code: str | None = None  # full generated source — powers the web Code tab
    last_run_id: str | None = None
    last_run_result: str | None = None  # PASSED | FAILED | SKIPPED | ERROR
    last_run_at: datetime | None = None
    last_failure_reason: str | None = None
    last_duration_ms: int | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    steps: list[TestStep] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
```

### 2.3 Capability + autonomy snapshots

```python
# packages/shared/domain/capability.py
from .base import DomainModel
from .enums import Tier, AutonomyLevel


class CapabilityFeatures(DomainModel):
    tcm: bool = True
    deterministic_run: bool = True
    mcp_plugins: bool = True
    ai_generation: bool = False
    ai_diagnosis: bool = False
    code_export: bool = True
    rag: bool = False
    embeddings: str = "none"  # "none" | "fastembed" | "openai" | "cohere"


class WorkspaceCapability(DomainModel):
    workspace_id: str
    tier: Tier
    autonomy_level: AutonomyLevel
    features: CapabilityFeatures
    updated_at: datetime
```

### 2.4 LLM config (write-only secrets)

```python
# packages/shared/domain/llm_config.py
from .base import DomainModel


class LLMConfigPublic(DomainModel):
    """Returned by API — `api_key` is never serialised."""
    id: str
    workspace_id: str
    provider: str       # "anthropic" | "openai" | "ollama" | …
    model: str
    config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_validated_at: datetime | None = None


class LLMConfigWrite(DomainModel):
    provider: str
    model: str
    api_key: str = Field(..., min_length=1, repr=False)
    config: dict[str, Any] = Field(default_factory=dict)
```

### 2.5 MCP provider registry

```python
# packages/shared/domain/mcp.py
from .base import DomainModel
from .enums import McpTransport


class McpProviderPublic(DomainModel):
    id: str
    workspace_id: str
    name: str
    kind: str  # "browser-use" | "playwright" | "api" | "postgres" | "kubernetes" | "custom"
    endpoint: str
    transport: McpTransport
    config: dict[str, Any] = Field(default_factory=dict)
    is_default_for_target: dict[str, bool] = Field(default_factory=dict)
    health_status: str = "unknown"
    created_at: datetime


class McpProviderWrite(DomainModel):
    name: str
    kind: str
    endpoint: str
    transport: McpTransport
    config: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict, repr=False)
    is_default_for_target: dict[str, bool] = Field(default_factory=dict)
```

### 2.6 Runs, run steps, artifacts

```python
class Run(DomainModel):
    id: str
    public_id: str
    project_id: str
    name: str
    branch: str | None = None
    commit_sha: str | None = None
    env: str = "staging"
    trigger: RunTrigger
    triggered_by: str | None = None
    status: RunStatus = RunStatus.QUEUED
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    tier_at_runtime: Tier  # NEW
    total_steps: int = 0
    passed_steps: int = 0
    failed_steps: int = 0
    metadata_json: dict[str, Any] | None = Field(default=None, alias="metadata")
    created_at: datetime
```

### 2.7 Defects

```python
import uuid


class Defect(DomainModel):
    id: str
    public_id: str
    workspace_id: str
    test_case_id: str | None = None
    run_id: str | None = None
    requirement_id: str | None = None
    title: str
    description: str | None = None
    severity: Severity
    status: DefectStatus = DefectStatus.OPEN
    component: str | None = None
    assignee_id: uuid.UUID | None = None
    agent_diagnosis: str | None = None
    agent_diagnosis_kind: DiagnosisKind = DiagnosisKind.MANUAL_TRIAGE  # NEW
    agent_confidence: float | None = None
    stack_trace: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
```

### 2.8 Agent session, message, tool call (reproducibility)

```python
import uuid


class AgentSession(DomainModel):
    id: str
    workspace_id: str
    user_id: uuid.UUID | None
    kind: AgentSessionKind
    status: str = "active"
    model_id: str
    provider: str                          # NEW: "anthropic" | "openai" | …
    prompt_version_id: str | None = None   # NEW
    seed: int | None = None                # NEW
    temperature: float | None = None       # NEW
    cost_usd: Decimal | None = None        # NEW
    tokens_in: int = 0
    tokens_out: int = 0
    metadata_json: dict[str, Any] | None = Field(default=None, alias="metadata")
    started_at: datetime
    completed_at: datetime | None = None


class AgentToolCall(DomainModel):
    id: str
    message_id: str
    tool_name: str
    mcp_provider: str | None = None        # NEW (None if not MCP-routed)
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    status: str = "running"
    duration_ms: int | None = None
    error_msg: str | None = None
    created_at: datetime
```

---

## 3. SQLAlchemy 2.0 async ORM models

> ORM lives in `packages/db/models/`. Single `Base`, all models async-friendly. Lazy loading **disabled** by default (`lazy="raise"`); explicit `selectinload`/`joinedload` di service. Driver: `asyncpg` via `postgresql+asyncpg://…`.

### 3.1 Base + utilities

```python
# packages/db/models/base.py
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import MetaData, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from cuid2 import Cuid

_cuid = Cuid(length=24)
def cuid() -> str: return _cuid.generate()
# Exception: FK to `users.id` is UUID (FastAPI-Users base).


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
```

> **Naming convention — reserved attribute `metadata`.** Any column named `metadata` in DB is mapped to attribute `metadata_json` in Python because `metadata` is reserved on SQLAlchemy `DeclarativeBase` (it shadows `Base.metadata`). Pattern: `metadata_json: Mapped[dict | None] = mapped_column(JSONB, name="metadata")`. Corresponding Pydantic domain models use `metadata_json: ... = Field(alias="metadata")` so serialised JSON stays `"metadata": {...}` — the API contract in [API.md](./API.md) is unchanged. Tables affected: `runs`, `artifacts`, `agent_sessions`, `agent_messages`, `document_chunks`, `audit_logs`.

### 3.2 Tenancy

```python
# packages/db/models/tenancy.py
from __future__ import annotations
import uuid
from sqlalchemy import String, ForeignKey, UniqueConstraint, Index, Enum as SAEnum, DateTime, Boolean, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from .base import Base, TimestampMixin, cuid
from packages.shared.domain.enums import Role


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    region: Mapped[str] = mapped_column(String(32), default="ap-southeast-1")

    # NEW (M1d) — controls `STEPS_REQUIRE_CODE_IN_ZERO_LLM` enforcement
    # (see CAPABILITY_TIERS §6.3). When true (default), the ZERO-tier validator
    # rejects test steps without executable code; flipping to false lets a
    # workspace stage manual-only cases before the runner is configured.
    strict_zero_validation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    # NEW (M1d) — workspace-scoped MCP routing override map, per MCP_PLUGINS §4.1.
    # Shape: {"<target_kind>": "<mcp_provider_name>"}; merged below the
    # suite-level override (Suite.mcp_routing_overrides) at resolve time.
    mcp_routing_overrides: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="'{}'",
    )

    memberships: Mapped[list["Membership"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    projects: Mapped[list["Project"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class User(SQLAlchemyBaseUserTableUUID, Base):
    """
    Canonical users table for Suitest. Extends FastAPI-Users'
    `fastapi_users_db_sqlalchemy.SQLAlchemyBaseUserTableUUID` — that base
    contributes `id (UUID, PK)`, `email`, `hashed_password`, `is_active`,
    `is_superuser`, `is_verified`. Suitest adds the columns below.

    Migration responsibility:
      - **M0 task 7** (FastAPI-Users setup) creates the base `users` + `oauth_account`
        tables via the FastAPI-Users initial migration (Alembic rev N).
      - **M1a `users` extension** is a separate Alembic migration (rev N+M) that
        adds `name`, `avatar_url`, `created_at`/`updated_at` — additive only,
        keeps the FastAPI-Users base untouched.
    """
    __tablename__ = "users"

    # Suitest-specific additions on top of the FastAPI-Users base.
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    # NOTE: `id` is **UUID** (from the FastAPI-Users base) — different from the
    # cuid2 strings used elsewhere. All FK columns that point at `users.id`
    # must therefore be declared as UUID, not String(30). See e.g.
    # `memberships.user_id`, `audit_logs.user_id`, `agent_sessions.user_id`.


class Membership(Base, TimestampMixin):
    __tablename__ = "memberships"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[Role] = mapped_column(SAEnum(Role, name="role"), default=Role.QA, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship()

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_memberships_workspace_user"),
        Index("ix_memberships_user_id", "user_id"),
    )
```

### 3.3 Projects, suites

```python
# packages/db/models/project.py
class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2048))

    # NEW (M1d) — optional pinned smoke suite used as the gating target for
    # webhook-triggered runs (M1d-16) and for the autopilot "promote to gating"
    # action (M1d-26). NULL means project has no gating suite configured;
    # webhook handler should reject the request with 422 in that case.
    gating_suite_id: Mapped[str | None] = mapped_column(
        String(30), ForeignKey("suites.id"), nullable=True,
    )

    workspace: Mapped[Workspace] = relationship(back_populates="projects")
    suites: Mapped[list["Suite"]] = relationship(back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("workspace_id", "slug", name="uq_projects_workspace_slug"),)


class Suite(Base, TimestampMixin):
    __tablename__ = "suites"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2048))
    order: Mapped[int] = mapped_column(default=0)

    # NEW (M1d) — suite-scoped MCP routing override, per MCP_PLUGINS §4.1.
    # Precedence: suite > workspace > registry default. Shape mirrors
    # Workspace.mcp_routing_overrides: {"<target_kind>": "<mcp_provider_name>"}.
    mcp_routing_overrides: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="'{}'",
    )

    # NEW (M1d) — soft-delete tombstone. Set by `DELETE /suites/:id`
    # (cascade soft-delete via `confirmCascade=true`) and cleared by
    # `POST /suites/:id/restore`. List endpoints filter `deleted_at IS NULL`
    # by default; admin queries opt-in via `includeDeleted=true`. 30-day
    # retention then hard-purge sweeper (deferred to M2+).
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    project: Mapped[Project] = relationship(back_populates="suites")

    __table_args__ = (
        Index("ix_suites_project_id", "project_id"),
        # Partial index — fast lookup of active (non-deleted) suites scoped
        # by workspace via JOIN to projects. Covers the default list query.
        Index(
            "ix_suites_project_active",
            "project_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
```

### 3.4 Test cases, steps (with `mcp_provider`, `target_kind`)

```python
# packages/db/models/case.py
import uuid
from sqlalchemy import Text, Integer, ForeignKey, UniqueConstraint, Index, Enum as SAEnum, JSON
from sqlalchemy.dialects.postgresql import JSONB, UUID
from packages.shared.domain.enums import (
    CaseSource, CaseStatus, Priority, TargetKind,
)


class TestCase(Base, TimestampMixin):
    __tablename__ = "test_cases"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    suite_id: Mapped[str] = mapped_column(ForeignKey("suites.id", ondelete="CASCADE"), nullable=False)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    preconditions: Mapped[str | None] = mapped_column(Text)
    source: Mapped[CaseSource] = mapped_column(SAEnum(CaseSource, name="case_source"), nullable=False)
    status: Mapped[CaseStatus] = mapped_column(SAEnum(CaseStatus, name="case_status"), default=CaseStatus.ACTIVE)
    priority: Mapped[Priority] = mapped_column(SAEnum(Priority, name="priority"), default=Priority.P2)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    generated_by: Mapped[str | None] = mapped_column(String(64))
    generated_from: Mapped[dict | None] = mapped_column(JSONB)
    estimated_ms: Mapped[int | None] = mapped_column(Integer)
    # Phase 2 (lifecycle ingest) — migration 0040_tcm_automation_lastrun
    automation_file_path: Mapped[str | None] = mapped_column(String(512))
    automation_code: Mapped[str | None] = mapped_column(Text)
    # Phase 2b (deterministic translate + review gate) — migration 0041_tcm_automation_review.
    # automation_status: NULL = none | "draft" (awaiting review) | "approved" (runner may pin & run).
    # State machine + runner guard = suitest_shared.domain.automation_review.
    automation_status: Mapped[str | None] = mapped_column(String(16))
    automation_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    automation_reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    last_run_id: Mapped[str | None] = mapped_column(String(32))
    last_run_result: Mapped[str | None] = mapped_column(String(16))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_reason: Mapped[str | None] = mapped_column(Text)
    last_duration_ms: Mapped[int | None] = mapped_column(Integer)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # NEW (M1d) — manual sort key within a suite. Drives the UI drag-reorder
    # endpoint (M1d-12) and the suite execution order in deterministic runs.
    # Default 0; ties broken by `created_at` ASC at the service layer.
    order_in_suite: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", index=True,
    )

    suite: Mapped[Suite] = relationship()
    steps: Mapped[list["TestStep"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="TestStep.order",
    )
    tags: Mapped[list["CaseTag"]] = relationship(cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_test_cases_suite_status", "suite_id", "status"),
        Index("ix_test_cases_source", "source"),
        Index("ix_test_cases_deleted_at", "deleted_at"),
        Index("ix_test_cases_suite_order", "suite_id", "order_in_suite"),
    )


class TestStep(Base):
    __tablename__ = "test_steps"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSONB)

    # NEW — per-step MCP routing
    mcp_provider: Mapped[str] = mapped_column(String(64), default="playwright-mcp", nullable=False)
    target_kind: Mapped[TargetKind] = mapped_column(
        SAEnum(TargetKind, name="target_kind"),
        default=TargetKind.FE_WEB,
        nullable=False,
    )

    case: Mapped[TestCase] = relationship(back_populates="steps")

    __table_args__ = (
        UniqueConstraint("case_id", "order", name="uq_test_steps_case_order"),
        Index("ix_test_steps_mcp_provider", "mcp_provider"),
        Index("ix_test_steps_target_kind", "target_kind"),
    )

    # NOTE: `executable` is intentionally NOT a column — it depends on workspace tier
    # at read time. See domain model `TestStep.executable(tier)`.


class CaseTag(Base):
    __tablename__ = "case_tags"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False)
    tag: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("case_id", "tag", name="uq_case_tags_case_tag"),
        Index("ix_case_tags_tag", "tag"),
    )
```

### 3.5 Requirements & traceability

```python
class Requirement(Base, TimestampMixin):
    __tablename__ = "requirements"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(255))
    external_url: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (Index("ix_requirements_project_id", "project_id"),)


class RequirementLink(Base):
    __tablename__ = "requirement_links"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False)
    case_id: Mapped[str] = mapped_column(ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (UniqueConstraint("requirement_id", "case_id", name="uq_requirement_links_req_case"),)
```

### 3.6 Runs, RunStep, Artifact

```python
# packages/db/models/run.py
from packages.shared.domain.enums import (
    RunStatus, RunTrigger, StepOutcome, ArtifactKind, Tier,
)


class Run(Base, TimestampMixin):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    branch: Mapped[str | None] = mapped_column(String(120))
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    env: Mapped[str] = mapped_column(String(32), default="staging")
    trigger: Mapped[RunTrigger] = mapped_column(SAEnum(RunTrigger, name="run_trigger"), nullable=False)
    triggered_by: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[RunStatus] = mapped_column(SAEnum(RunStatus, name="run_status"), default=RunStatus.QUEUED)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    # NEW — captured at run start so historical runs remain reproducible
    tier_at_runtime: Mapped[Tier] = mapped_column(SAEnum(Tier, name="tier"), nullable=False)

    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    passed_steps: Mapped[int] = mapped_column(Integer, default=0)
    failed_steps: Mapped[int] = mapped_column(Integer, default=0)
    # `metadata` is reserved on DeclarativeBase → Python attr renamed to `metadata_json`;
    # DB column name stays `metadata`. See §3.1 naming-convention note.
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, name="metadata")

    __table_args__ = (
        Index("ix_runs_project_status", "project_id", "status"),
        Index("ix_runs_created_at", "created_at"),
        Index("ix_runs_tier", "tier_at_runtime"),
    )

    # --- Run dedup (M1d) ---------------------------------------------------
    # Webhook-triggered and ad-hoc "run now" requests are de-duplicated at the
    # **application layer** via Redis SETNX with key
    #   `dedup:run:{project_id}:{commit_sha}:{trigger}`
    # and a 60-second TTL. The first request that wins the SETNX proceeds to
    # create the Run row; subsequent requests within the TTL window return
    # 409 with the existing run id.
    #
    # **No Postgres partial unique index for this case** — Postgres rejects
    # non-IMMUTABLE expressions (`NOW()`, `CURRENT_TIMESTAMP`, ...) inside
    # partial-index WHERE clauses, so a TTL-style index like
    #   `UNIQUE (project_id, commit_sha, trigger) WHERE created_at > NOW() - '60s'`
    # cannot be created. Redis is the source of truth for the dedup window.


class RunStep(Base, TimestampMixin):
    __tablename__ = "run_steps"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    case_id: Mapped[str] = mapped_column(ForeignKey("test_cases.id"), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[StepOutcome] = mapped_column(SAEnum(StepOutcome, name="step_outcome"), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    stdout: Mapped[str | None] = mapped_column(Text)
    stderr: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_stack: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_run_steps_run_outcome", "run_id", "outcome"),)


class Artifact(Base, TimestampMixin):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    run_step_id: Mapped[str] = mapped_column(ForeignKey("run_steps.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[ArtifactKind] = mapped_column(SAEnum(ArtifactKind, name="artifact_kind"), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)  # s3:// or file://
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    # `metadata` reserved on DeclarativeBase → Python attr `metadata_json`, DB column `metadata`.
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, name="metadata")

    __table_args__ = (Index("ix_artifacts_run_step_id", "run_step_id"),)
```

### 3.7 Defects + External issues

```python
# packages/db/models/defect.py
import uuid
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID
from packages.shared.domain.enums import Severity, DefectStatus, DiagnosisKind


class Defect(Base, TimestampMixin):
    __tablename__ = "defects"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    test_case_id: Mapped[str | None] = mapped_column(ForeignKey("test_cases.id"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"))
    requirement_id: Mapped[str | None] = mapped_column(ForeignKey("requirements.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[Severity] = mapped_column(SAEnum(Severity, name="severity"), nullable=False)
    status: Mapped[DefectStatus] = mapped_column(SAEnum(DefectStatus, name="defect_status"), default=DefectStatus.OPEN)
    component: Mapped[str | None] = mapped_column(String(120))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    agent_diagnosis: Mapped[str | None] = mapped_column(Text)

    # NEW — diagnosis kind drives downstream automation (retry / block / triage-manual)
    agent_diagnosis_kind: Mapped[DiagnosisKind] = mapped_column(
        SAEnum(DiagnosisKind, name="diagnosis_kind"),
        default=DiagnosisKind.MANUAL_TRIAGE,
        nullable=False,
    )
    agent_confidence: Mapped[float | None] = mapped_column()
    stack_trace: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_defects_workspace_status", "workspace_id", "status"),
        Index("ix_defects_severity", "severity"),
        Index("ix_defects_diagnosis_kind", "agent_diagnosis_kind"),
        # NEW (M1d) — prevents DefectAutoFiler from double-filing the same
        # (run, case) pair on runner retry. Manual defects on the same pair
        # are still allowed because the predicate excludes them.
        Index(
            "uq_defects_auto_dedup",
            "run_id",
            "test_case_id",
            unique=True,
            postgresql_where=text("created_by = 'system'"),
        ),
    )


class ExternalIssue(Base, TimestampMixin):
    __tablename__ = "external_issues"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    defect_id: Mapped[str] = mapped_column(ForeignKey("defects.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_external_issues_provider_external"),)
```

### 3.8 Integrations (kind enum expanded)

```python
# packages/db/models/integration.py
from sqlalchemy import LargeBinary
from packages.shared.domain.enums import IntegrationKind


class Integration(Base, TimestampMixin):
    __tablename__ = "integrations"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[IntegrationKind] = mapped_column(SAEnum(IntegrationKind, name="integration_kind"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # secrets stored as AES-GCM blob — see §12
    secrets_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)

    status: Mapped[str] = mapped_column(String(32), default="active")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_integrations_workspace_kind", "workspace_id", "kind"),)
```

### 3.9 Agent (sessions / messages / tool calls) — reproducibility fields

```python
# packages/db/models/agent.py
import uuid
from sqlalchemy import Numeric, Float
from sqlalchemy.dialects.postgresql import UUID
from packages.shared.domain.enums import AgentSessionKind, MessageRole


class AgentSession(Base, TimestampMixin):
    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    kind: Mapped[AgentSessionKind] = mapped_column(SAEnum(AgentSessionKind, name="agent_session_kind"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active")
    model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)            # NEW
    prompt_version_id: Mapped[str | None] = mapped_column(                       # NEW
        ForeignKey("prompt_versions.id"),
    )
    seed: Mapped[int | None] = mapped_column(Integer)                            # NEW
    temperature: Mapped[float | None] = mapped_column(Float)                     # NEW
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))             # NEW
    # `metadata` reserved on DeclarativeBase → Python attr `metadata_json`, DB column `metadata`.
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, name="metadata")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_agent_sessions_workspace_kind", "workspace_id", "kind"),
        Index("ix_agent_sessions_provider", "provider"),
    )


class AgentMessage(Base, TimestampMixin):
    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[MessageRole] = mapped_column(SAEnum(MessageRole, name="message_role"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # `metadata` reserved on DeclarativeBase → Python attr `metadata_json`, DB column `metadata`.
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, name="metadata")

    __table_args__ = (Index("ix_agent_messages_session_id", "session_id"),)


class AgentToolCall(Base, TimestampMixin):
    __tablename__ = "agent_tool_calls"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    message_id: Mapped[str] = mapped_column(ForeignKey("agent_messages.id", ondelete="CASCADE"), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    mcp_provider: Mapped[str | None] = mapped_column(String(64))   # NEW
    input: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), default="running")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_msg: Mapped[str | None] = mapped_column(Text)
```

### 3.10 Documents + DocumentChunk (variable-dim pgvector)

```python
# packages/db/models/document.py
from pgvector.sqlalchemy import Vector
from packages.shared.domain.enums import DocumentKind


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[DocumentKind] = mapped_column(SAEnum(DocumentKind, name="document_kind"), nullable=False)
    source: Mapped[str] = mapped_column(String(1024), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (Index("ix_documents_workspace_kind", "workspace_id", "kind"),)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Variable dim — actual dimension enforced per-workspace by check constraint
    # added in a migration (see §13 vector dim matrix). Vector(None) → no fixed dim.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(None))

    # `metadata` reserved on DeclarativeBase → Python attr `metadata_json`, DB column `metadata`.
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, name="metadata")

    __table_args__ = (
        Index("ix_document_chunks_document_id", "document_id"),
        # HNSW index added per-workspace via raw SQL migration (see §7).
    )
```

### 3.11 Audit log

```python
import uuid
from sqlalchemy.dialects.postgresql import UUID


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # `metadata` reserved on DeclarativeBase → Python attr `metadata_json`, DB column `metadata`.
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, name="metadata")
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_audit_logs_workspace_created", "workspace_id", "created_at"),)
```

> **Autonomy-extension fields live in `metadata_json`.** The JSONB `metadata`
> column is the canonical home for the autonomy-overlay fields documented in
> AUTONOMY.md §12 — `actor_type`, `actor_id`, `target_type`, `target_id`,
> `autonomy_level_at_time`, `overrides_at_time`, `before`, `after`,
> `correlation_id`, and `reason`. No schema change is required: writers MUST
> populate these keys under `metadata_json` rather than introducing new top-level
> columns. AUTONOMY.md §12 will be revised to reference this schema instead of
> duplicating it.

---

## 4. NEW tables for OSS pivot

### 4.1 `llm_configs` — workspace LLM provider

```python
# packages/db/models/llm_config.py
from sqlalchemy import LargeBinary, Boolean


class LLMConfig(Base, TimestampMixin):
    __tablename__ = "llm_configs"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)

    # AES-GCM (see §12). Always nullable so ZERO tier can have a row with no key.
    api_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)

    config_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_llm_configs_workspace_active", "workspace_id", "is_active"),
    )
```

### 4.2 `workspace_capabilities` — materialized capability snapshot

```python
# packages/db/models/workspace_capability.py
from packages.shared.domain.enums import Tier, AutonomyLevel


class WorkspaceCapability(Base):
    __tablename__ = "workspace_capabilities"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    tier: Mapped[Tier] = mapped_column(SAEnum(Tier, name="tier"), nullable=False)
    autonomy_level: Mapped[AutonomyLevel] = mapped_column(
        SAEnum(AutonomyLevel, name="autonomy_level"), default=AutonomyLevel.MANUAL,
    )
    features_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (Index("ix_workspace_capabilities_tier", "tier"),)
```

> Refreshed on **any** of: LLM config change, autonomy change, MCP provider toggle, embeddings backend env update.

### 4.3 `mcp_providers` — per-workspace registry

```python
# packages/db/models/mcp_provider.py
from packages.shared.domain.enums import McpTransport


class McpProvider(Base, TimestampMixin):
    __tablename__ = "mcp_providers"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    # NULL for bundled/global providers; FK to workspace for user-registered
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    # browser-use | playwright | api | postgres | kubernetes | graphql | grpc |
    # appium | mongo | mysql | custom
    endpoint: Mapped[str] = mapped_column(String(1024), nullable=False)
    transport: Mapped[McpTransport] = mapped_column(
        SAEnum(McpTransport, name="mcp_transport"), nullable=False,
    )
    config_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    secrets_json_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    is_default_for_target: Mapped[dict] = mapped_column(JSONB, default=dict)
    # e.g. {"BE_REST": true} → autoroute target_kind BE_REST to this provider

    # NEW (M1d) — provenance/version pins recorded at install or first handshake.
    # See MCP_PLUGINS §13. All four nullable; the resolver writes whichever
    # the transport exposes (stdio → command_pin + optional git_ref;
    # docker/image → image_pin; SSE/WS → version_pin from handshake).
    command_pin: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # e.g. "jirac-mcp@jira-mcp-v2.0.1"
    image_pin: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # e.g. "ghcr.io/suitest/postgres-mcp:0.7.1"
    version_pin: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # captured from SSE/WS handshake (server's `serverInfo.version`)
    git_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # for stdio (git) transport — commit SHA or tag

    health_status: Mapped[str] = mapped_column(String(32), default="unknown")
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # false = registered but not active in routing (e.g. bundled jirac-mcp before integration connect)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )

    __table_args__ = (
        Index("ix_mcp_providers_workspace_kind", "workspace_id", "kind"),
        # Postgres treats NULLs as distinct in unique indexes, so bundled rows
        # (workspace_id IS NULL) can repeat the same `name` without collision.
        # If you need to forbid duplicate bundled names, swap to a partial
        # unique index `WHERE workspace_id IS NOT NULL` plus a second partial
        # unique index `(name) WHERE workspace_id IS NULL`.
        UniqueConstraint("workspace_id", "name", name="uq_mcp_providers_workspace_name"),
    )
```

### 4.4 `generator_runs` — deterministic generators traceability

```python
import uuid
from sqlalchemy.dialects.postgresql import UUID


class GeneratorRun(Base):
    __tablename__ = "generator_runs"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    # openapi | recorder | heuristic_crawl | prd | url_semantic | mcp_discovery
    input_meta_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    output_case_ids_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    __table_args__ = (
        Index("ix_generator_runs_workspace_source", "workspace_id", "source"),
        Index("ix_generator_runs_created_at", "created_at"),
    )
```

### 4.5 `prompt_versions` — versioned prompts

```python
class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)  # "v1/generate-from-prd"
    version: Mapped[str] = mapped_column(String(32), nullable=False)  # semver
    content: Mapped[str] = mapped_column(Text, nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)  # sha256(content)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_prompt_versions_name_version"),
        Index("ix_prompt_versions_hash", "hash"),
    )
```

### 4.6 `eval_runs` — schema present v1.0, UI v1.x

```python
class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    eval_suite_name: Mapped[str] = mapped_column(String(120), nullable=False)
    fixtures_count: Mapped[int] = mapped_column(Integer, nullable=False)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version_id: Mapped[str | None] = mapped_column(ForeignKey("prompt_versions.id"))
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    results_json: Mapped[dict] = mapped_column(JSONB, default=dict)

    __table_args__ = (Index("ix_eval_runs_workspace_suite", "workspace_id", "eval_suite_name"),)
```

### 4.7 `code_exports` — exported test code

```python
import uuid
from sqlalchemy.dialects.postgresql import UUID


class CodeExport(Base):
    __tablename__ = "code_exports"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False)
    target: Mapped[str] = mapped_column(String(32), nullable=False)  # playwright | cypress | selenium
    exported_code_text: Mapped[str] = mapped_column(Text, nullable=False)
    exported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    __table_args__ = (
        Index("ix_code_exports_case_target", "case_id", "target"),
    )
```

---

## 5. Modified tables (delta summary)

| Table | Change | Notes |
|-------|--------|-------|
| `test_steps` | + `mcp_provider TEXT NOT NULL DEFAULT 'playwright-mcp'` | per-step MCP routing |
| `test_steps` | + `target_kind ENUM target_kind NOT NULL DEFAULT 'FE_WEB'` | classification used by router |
| `test_steps` | `executable` **NOT a column** — computed in domain `TestStep.executable(tier)` |
| `agent_sessions` | + `prompt_version_id FK prompt_versions(id) NULL` | reproducibility |
| `agent_sessions` | + `seed INT NULL` | LLM determinism |
| `agent_sessions` | + `temperature FLOAT NULL` | LLM determinism |
| `agent_sessions` | + `cost_usd NUMERIC(10,4) NULL` | LiteLLM cost tracking |
| `agent_sessions` | + `provider TEXT NOT NULL` | multi-provider observability |
| `agent_tool_calls` | + `mcp_provider TEXT NULL` | tool may be MCP-routed |
| `integrations.kind` | enum + `MCP_API, MCP_POSTGRES, MCP_KUBERNETES, MCP_GRAPHQL, MCP_GRPC, MCP_APPIUM, MCP_MONGO, MCP_MYSQL` | (Existing: `GITHUB, GITLAB, JENKINS, JIRA, LINEAR, SLACK, MCP_BROWSER_USE, MCP_PLAYWRIGHT, MCP_CUSTOM, OPENAPI`) |
| `document_chunks.embedding` | `Vector(1536)` → `Vector(None)` + per-workspace dim check | variable-dim, see §13 |
| `defects` | + `agent_diagnosis_kind ENUM diagnosis_kind NOT NULL DEFAULT 'MANUAL_TRIAGE'` | drives auto-action; `MANUAL_TRIAGE` is ZERO default |
| `runs` | + `tier_at_runtime ENUM tier NOT NULL` | reproducibility |
| `runs` | dedup via Redis SETNX (app-layer) — **no** Postgres partial unique index | Postgres rejects `NOW()` in partial-index predicates; see §3.6 note |
| `case_source` enum | + `RECORDER, HEURISTIC_CRAWL` (existing: `MANUAL, AI, MCP, IMPORT`) | deterministic generator sources |
| `artifacts.url` | semantic: `s3://` (MinIO/S3) **or** `file://` (single-host volume) | OSS-friendly |
| `workspaces` | + `strict_zero_validation BOOL NOT NULL DEFAULT true` | toggles `STEPS_REQUIRE_CODE_IN_ZERO_LLM` per workspace (CAPABILITY_TIERS §6.3) |
| `workspaces` | + `mcp_routing_overrides JSONB NOT NULL DEFAULT '{}'` | workspace-scoped MCP routing override (MCP_PLUGINS §4.1) |
| `projects` | + `gating_suite_id FK suites(id) NULL` | pinned smoke suite for webhook gating (M1d-16, M1d-26) |
| `suites` | + `mcp_routing_overrides JSONB NOT NULL DEFAULT '{}'` | suite-scoped MCP routing override (precedes workspace) |
| `suites` | + `deleted_at TIMESTAMPTZ NULL` + partial idx `ix_suites_project_active(project_id) WHERE deleted_at IS NULL` | soft-delete tombstone for `DELETE /suites/:id` + `POST /suites/:id/restore` (M1d-4) |
| `test_cases` | + `order_in_suite INT NOT NULL DEFAULT 0` (indexed) | drives suite drag-reorder (M1d-12) |
| `mcp_providers` | + `command_pin / image_pin / version_pin / git_ref` (all NULL) | provenance pins per MCP_PLUGINS §13 |
| `mcp_providers` | `workspace_id` → nullable | NULL = bundled/global provider; NOT NULL = workspace-scoped (M1d-1) |
| `mcp_providers` | + `enabled BOOLEAN NOT NULL DEFAULT TRUE` | false = registered but inactive in routing (M1d-1; bundled `jirac-mcp` + `github-mcp` seeded `enabled=false`) |
| `defects` | partial UNIQUE `(run_id, test_case_id) WHERE created_by = 'system'` | prevents `DefectAutoFiler` double-file on runner retry |

---

## 6. Enums

> `packages/shared/domain/enums.py`. Python `enum.StrEnum` (3.11+) so they serialise as strings.

```python
from enum import StrEnum, auto


class Role(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    QA = "QA"
    VIEWER = "VIEWER"


class CaseSource(StrEnum):
    MANUAL = "MANUAL"
    AI = "AI"
    MCP = "MCP"
    IMPORT = "IMPORT"
    RECORDER = "RECORDER"            # NEW
    HEURISTIC_CRAWL = "HEURISTIC_CRAWL"  # NEW


class Priority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class CaseStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PASS = "PASS"
    FAIL = "FAIL"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class RunTrigger(StrEnum):
    MANUAL = "MANUAL"
    SCHEDULED = "SCHEDULED"
    CI_PUSH = "CI_PUSH"
    CI_PR = "CI_PR"
    WEBHOOK = "WEBHOOK"
    AGENT = "AGENT"


class StepOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    ERROR = "ERROR"
    PENDING = "PENDING"


class ArtifactKind(StrEnum):
    SCREENSHOT = "SCREENSHOT"
    HAR = "HAR"
    DOM_SNAPSHOT = "DOM_SNAPSHOT"
    VIDEO = "VIDEO"
    CONSOLE_LOG = "CONSOLE_LOG"
    TRACE = "TRACE"
    CUSTOM = "CUSTOM"


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DefectStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    WONT_FIX = "WONT_FIX"


class IntegrationKind(StrEnum):
    GITHUB = "GITHUB"
    GITLAB = "GITLAB"
    JENKINS = "JENKINS"
    JIRA = "JIRA"
    LINEAR = "LINEAR"
    SLACK = "SLACK"
    MCP_BROWSER_USE = "MCP_BROWSER_USE"
    MCP_PLAYWRIGHT = "MCP_PLAYWRIGHT"
    MCP_CUSTOM = "MCP_CUSTOM"
    OPENAPI = "OPENAPI"
    # NEW for OSS pivot
    MCP_API = "MCP_API"
    MCP_POSTGRES = "MCP_POSTGRES"
    MCP_KUBERNETES = "MCP_KUBERNETES"
    MCP_GRAPHQL = "MCP_GRAPHQL"
    MCP_GRPC = "MCP_GRPC"
    MCP_APPIUM = "MCP_APPIUM"
    MCP_MONGO = "MCP_MONGO"
    MCP_MYSQL = "MCP_MYSQL"


class AgentSessionKind(StrEnum):
    GENERATION = "GENERATION"
    EXECUTION = "EXECUTION"
    DIAGNOSIS = "DIAGNOSIS"
    CONVERSATION = "CONVERSATION"


class MessageRole(StrEnum):
    USER = "USER"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"
    TOOL = "TOOL"


class DocumentKind(StrEnum):
    PRD = "PRD"
    OPENAPI = "OPENAPI"
    URL_CRAWL = "URL_CRAWL"
    LINEAR_ISSUE = "LINEAR_ISSUE"
    NOTION_PAGE = "NOTION_PAGE"
    CUSTOM = "CUSTOM"


# NEW enums for OSS pivot
class TargetKind(StrEnum):
    BE_REST = "BE_REST"
    BE_GRAPHQL = "BE_GRAPHQL"
    BE_GRPC = "BE_GRPC"
    FE_WEB = "FE_WEB"
    FE_MOBILE = "FE_MOBILE"
    DATA = "DATA"
    INFRA = "INFRA"
    CUSTOM = "CUSTOM"


class Tier(StrEnum):
    ZERO = "ZERO"
    LOCAL = "LOCAL"
    CLOUD = "CLOUD"


class AutonomyLevel(StrEnum):
    MANUAL = "manual"
    ASSIST = "assist"
    SEMI_AUTO = "semi_auto"
    AUTO = "auto"


class DiagnosisKind(StrEnum):
    REGRESSION = "REGRESSION"
    FLAKE = "FLAKE"
    INFRA = "INFRA"
    SPEC_DRIFT = "SPEC_DRIFT"
    MANUAL_TRIAGE = "MANUAL_TRIAGE"  # ZERO tier rule-based fallback


class McpTransport(StrEnum):
    STDIO = "stdio"
    SSE = "sse"
    WS = "ws"
```

---

## 7. Indexes & query patterns

### 7.1 Hot queries → indexes

| Query | Index |
|-------|-------|
| List cases in suite by status | `ix_test_cases_suite_status (suite_id, status)` |
| Filter cases by source | `ix_test_cases_source (source)` |
| Cases pending hard-delete | `ix_test_cases_deleted_at (deleted_at)` |
| Active (non-deleted) suites in project | `ix_suites_project_active (project_id) WHERE deleted_at IS NULL` |
| Steps by MCP provider (debug routing) | `ix_test_steps_mcp_provider (mcp_provider)` |
| Steps by target kind | `ix_test_steps_target_kind (target_kind)` |
| List runs in project by status | `ix_runs_project_status (project_id, status)` |
| Recent runs sorted by time | `ix_runs_created_at (created_at DESC)` |
| Runs by tier (capacity planning) | `ix_runs_tier (tier_at_runtime)` |
| Failed steps in a run | `ix_run_steps_run_outcome (run_id, outcome)` |
| Open defects in workspace | `ix_defects_workspace_status (workspace_id, status)` |
| Defects by diagnosis kind (auto-action) | `ix_defects_diagnosis_kind (agent_diagnosis_kind)` |
| Tag filter | `ix_case_tags_tag (tag)` |
| Membership lookup | `ix_memberships_user_id (user_id)` |
| Audit history | `ix_audit_logs_workspace_created (workspace_id, created_at DESC)` |
| Active LLM config per workspace | `ix_llm_configs_workspace_active (workspace_id, is_active)` |
| MCP provider lookup by kind | `ix_mcp_providers_workspace_kind (workspace_id, kind)` |
| Active MCP providers (routing) | `ix_mcp_providers_active (workspace_id) WHERE enabled = true` (optional partial idx — add when routing hot-path requires it) |
| Generator runs history | `ix_generator_runs_workspace_source (workspace_id, source)` |
| Agent sessions by provider | `ix_agent_sessions_provider (provider)` |
| Fast suite-scoped case reorder | `ix_test_cases_suite_order (suite_id, order_in_suite)` |

#### Partial unique indexes

| Constraint | Definition | Purpose |
|------------|-----------|---------|
| `uq_defects_auto_dedup` | `UNIQUE ON defects(run_id, test_case_id) WHERE created_by = 'system'` | Prevents `DefectAutoFiler` from double-filing on runner retry. Manual defects on the same `(run, case)` pair are still allowed because the predicate excludes them. |

> **Why not a partial unique index for `runs` dedup?** Postgres rejects partial-index `WHERE` clauses that reference non-IMMUTABLE functions such as `NOW()` / `CURRENT_TIMESTAMP`, so a TTL-style index like `WHERE created_at > NOW() - INTERVAL '60 seconds'` is invalid. Run dedup is therefore enforced at the application layer — see §3.6 note on the Redis SETNX pattern.

### 7.2 Vector search (pgvector, HNSW)

Per-workspace HNSW index, created in a workspace-bootstrap migration:

```sql
-- packages/db/alembic/versions/xxx_pgvector_hnsw.py (op.execute)
CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw
  ON document_chunks
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
```

Query (top-k similar chunks for a workspace):

```python
# packages/agent/retrieval.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

async def search_chunks(db: AsyncSession, workspace_id: str, query_vec: list[float], k: int = 8):
    stmt = (
        select(DocumentChunk, Document)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.workspace_id == workspace_id)
        .order_by(DocumentChunk.embedding.cosine_distance(query_vec))
        .limit(k)
    )
    return (await db.execute(stmt)).all()
```

Used by the agent to retrieve PRD/OpenAPI context when generating cases (CLOUD/LOCAL only — ZERO has `embeddings=none` and short-circuits to FTS).

### 7.3 FTS fallback (ZERO tier, no embeddings)

Postgres full-text on `documents.title || ' ' || coalesce(document_chunks.content,'')` via `tsvector` generated column + GIN index. Added in a separate migration so it ships in ZERO without pulling pgvector ops.

---

## 8. Public ID generation

Same approach as before — Postgres sequence **per workspace, per prefix**:

```sql
CREATE OR REPLACE FUNCTION generate_public_id(prefix TEXT, workspace_id TEXT)
RETURNS TEXT AS $$
DECLARE
  seq_name TEXT := 'pubid_' || replace(workspace_id, '-', '_') || '_' || prefix;
  next_val BIGINT;
BEGIN
  EXECUTE format('CREATE SEQUENCE IF NOT EXISTS %I START 1000', seq_name);
  EXECUTE format('SELECT nextval(%L)', seq_name) INTO next_val;
  RETURN prefix || '-' || next_val;
END;
$$ LANGUAGE plpgsql;
```

Service-layer wrapper:

```python
# packages/db/public_id.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

async def generate_public_id(db: AsyncSession, prefix: str, workspace_id: str) -> str:
    row = await db.execute(
        text("SELECT generate_public_id(:p, :w) AS pid"),
        {"p": prefix, "w": workspace_id},
    )
    return row.scalar_one()
```

Prefix map: `TC-` (test case), `R-` (run), `REQ-` (requirement), `SUIT-` (defect).

---

## 9. Soft delete & retention

| Table | Policy |
|-------|--------|
| `test_cases.deleted_at` | Soft delete, 30-day retention then hard-purge cron |
| `suites.deleted_at` | Soft delete (cascade via `confirmCascade=true`); 30-day retention then hard-purge cron (sweeper deferred to M2+) |
| `runs` | Hard-delete after 180 days (configurable via `SUITEST_RUN_RETENTION_DAYS`) |
| `run_steps`, `artifacts` | Cascade-deleted with `runs`; object storage lifecycle separately |
| `defects` | **Never** deleted — close via `status=WONT_FIX` or `CLOSED` |
| `agent_sessions` + children | Cascade with workspace; no retention cap |
| `audit_logs` | Append-only, never deleted (compliance) |

Purge cron lives in `apps/worker/tasks/retention.py` (ARQ scheduled task).

---

## 10. Migrations workflow (Alembic)

```bash
# Generate new migration from model diff
uv run alembic revision --autogenerate -m "add llm_configs and capability tables"

# Inspect generated file in packages/db/alembic/versions/ — DO NOT trust autogen blindly

# Apply
uv run alembic upgrade head

# Rollback one step
uv run alembic downgrade -1

# Show current rev
uv run alembic current
```

**Rules:**

1. **Additive first.** Add column → deploy → backfill → switch code → drop old column in **next** release. No same-release column drops if existing code still reads it.
2. **No rename without shadow read.** Add new column, dual-write, migrate readers, drop old column.
3. **Enum changes:** `ADD VALUE` only (Postgres can't remove enum values without recreate). For a remove, do a full enum recreate in a dedicated migration with `op.execute()`.
4. **Vector dim changes:** Per-workspace check constraint dropped + recreated; reindex pgvector HNSW in `concurrently` mode.
5. **All Alembic files reviewed manually** — autogen misses `JSONB` defaults, `check_constraint`s, enum value additions, and pgvector index types.
6. **Deferred FKs.** FKs that span tables defined later in this document must be added via a follow-up Alembic migration **AFTER** both tables exist. Specifically: `agent_sessions.prompt_version_id` → `prompt_versions(id)` (see §3.9 ↔ §4.5) lives in migration **N+1**, not in the initial `agent_sessions` create-table migration. The doc is ordered for narrative clarity (core tenancy → run/agent core in §3, OSS-pivot additions in §4); migration ordering should be: create `prompt_versions` first → create `agent_sessions` without the FK → add FK constraint in a separate revision via `op.create_foreign_key(...)`. Same applies to `eval_runs.prompt_version_id`.

`alembic.ini` points at `packages/db/alembic/`; `env.py` uses async engine (`sqlalchemy.ext.asyncio`).

---

## 11. Seed data

`packages/db/seed.py` — idempotent Python script.

```bash
uv run python -m packages.db.seed
```

Creates workspace **Nusantara Retail** with same shape as before:

- 1 owner (`maya@suitest.io`), 2 members (`ari@`, `dimas@`)
- 1 project **E-commerce Web**
- 4 suites, 18 test cases mixing all `CaseSource` values (incl. `RECORDER`, `HEURISTIC_CRAWL`)
- 5 runs (mix `PASS/FAIL/ERROR`, all with `tier_at_runtime=ZERO`)
- 3 defects (mockup-matching) with `agent_diagnosis_kind=MANUAL_TRIAGE`
- 6 requirements + traceability links
- **8 integrations** — one row per realistic `IntegrationKind`. `OPENAPI` is **not** seeded as an integration (it's a document source — see §10 below):

  | name | kind | status |
  |------|------|--------|
  | GitHub (nusantara-retail) | `GITHUB` | connected |
  | GitLab (mirror) | `GITLAB` | disconnected |
  | Jenkins (internal CI) | `JENKINS` | disconnected |
  | Jira (Nusantara Retail) | `JIRA` | connected |
  | Linear (product) | `LINEAR` | disconnected |
  | Slack (#qa-alerts) | `SLACK` | connected |
  | Playwright MCP (bundled) | `MCP_PLAYWRIGHT` | connected |
  | Browser-Use MCP (staging) | `MCP_BROWSER_USE` | disconnected |
- 1 `LLMConfig` row inactive (provider=`none`)
- 1 `WorkspaceCapability` row tier=`ZERO`, autonomy=`manual`
- 2 `McpProvider` rows: `playwright-mcp` (default FE_WEB) + `api-mcp` (default BE_REST), both `health_status=unknown`
- 1 `PromptVersion` `v1/generate-from-prd` v1.0.0

Idempotency: `INSERT … ON CONFLICT DO NOTHING` for unique slugs; safe to re-run.

---

## 12. Encryption (AES-GCM)

All secrets (`llm_configs.api_key_encrypted`, `mcp_providers.secrets_json_encrypted`, `integrations.secrets_encrypted`) use **AES-256-GCM** with a single workspace-master key.

- Key source: `SUITEST_ENCRYPTION_KEY` env var, base64-encoded 32 bytes (`base64.urlsafe_b64decode`).
- Generated once at install via `uv run python -m packages.db.crypto keygen` (writes to `.env`).
- Helm chart: same env, sourced from `kubernetes.io/secret`.
- Optional KMS adapter (v1.x): `SUITEST_ENCRYPTION_BACKEND=kms` + AWS KMS / GCP KMS resolver.

```python
# packages/db/crypto.py
from __future__ import annotations
import os, base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _key() -> bytes:
    raw = os.environ.get("SUITEST_ENCRYPTION_KEY")
    if not raw:
        raise RuntimeError("SUITEST_ENCRYPTION_KEY not set (32 bytes base64).")
    key = base64.urlsafe_b64decode(raw)
    if len(key) != 32:
        raise RuntimeError("SUITEST_ENCRYPTION_KEY must decode to 32 bytes.")
    return key


def encrypt(plaintext: str, aad: bytes = b"") -> bytes:
    aes = AESGCM(_key())
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), aad)
    return nonce + ct  # [nonce(12) | ciphertext+tag]


def decrypt(blob: bytes, aad: bytes = b"") -> str:
    if blob is None:
        raise ValueError("nothing to decrypt")
    aes = AESGCM(_key())
    nonce, ct = blob[:12], blob[12:]
    return aes.decrypt(nonce, ct, aad).decode("utf-8")
```

Service-layer usage:

```python
# apps/api/src/services/llm_config_service.py
from packages.db.crypto import encrypt, decrypt

async def set_llm_config(db, workspace_id, write: LLMConfigWrite) -> LLMConfigPublic:
    row = await db.scalar(select(LLMConfig).where(LLMConfig.workspace_id == workspace_id))
    if not row:
        row = LLMConfig(workspace_id=workspace_id)
        db.add(row)
    row.provider = write.provider
    row.model = write.model
    row.api_key_encrypted = encrypt(write.api_key, aad=workspace_id.encode())
    row.config_json = write.config
    row.is_active = True
    await db.flush()
    return LLMConfigPublic.model_validate(row)
```

> Note: `aad` (additional authenticated data) is bound to `workspace_id` so a ciphertext copy-pasted into another workspace's row fails to decrypt — small but useful integrity guard.

---

## 13. Vector dimension matrix

| `SUITEST_EMBEDDINGS_BACKEND` | Provider | Model | Dim | Notes |
|------------------------------|----------|-------|-----|-------|
| `none` | (off) | — | n/a | ZERO default. RAG disabled, agent falls back to FTS. |
| `fastembed` | BAAI | `bge-small-en-v1.5` | **384** | Local CPU, no API key. Default for LOCAL tier. |
| `openai` | OpenAI | `text-embedding-3-small` | **1536** | CLOUD. Lower-cost option (`-large`=3072 also supported, must match check constraint). |
| `cohere` | Cohere | `embed-english-v3.0` | **1024** | CLOUD. |

Enforcement: per-workspace check constraint, set in a migration when the workspace's embeddings backend is selected:

```sql
ALTER TABLE document_chunks
  ADD CONSTRAINT ck_document_chunks_dim_<wsid>
  CHECK (array_length(embedding::real[], 1) = 384)
  NOT VALID;  -- existing rows tolerated
```

Workspaces can't switch backends without a re-index migration (drops old chunks for that workspace, re-embeds via worker job). UI surfaces this as a confirm dialog.

Default in Helm: `none`. Compose dev profile flips to `fastembed` so local devs see RAG without keys.

---

## 14. Glossary references

See [CLAUDE.md](../CLAUDE.md) §7 for product terms (TCM, MCP, Run, Suite, Gating, Flaky, Traceability, Defect, Artifact). Tier/Autonomy/MCP-specific terms live in their respective docs: [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md), [AUTONOMY.md](./AUTONOMY.md), [MCP_PLUGINS.md](./MCP_PLUGINS.md).
