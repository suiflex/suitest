# M2 — Deterministic Generators + MCP Plugin Expansion + Code Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 3 deterministic test generators (OpenAPI contract suite, Browser Recorder via Playwright MCP, Heuristic URL Crawler), target classifier (rule-based, no LLM), 5 additional bundled MCP providers (graphql, mongo, mysql, kubernetes, grpc), custom MCP registration UI + flow, mixed-MCP test case execution proven end-to-end via demo, and test code export to Playwright / Cypress / Selenium frameworks. All features available in ZERO tier (no LLM required).

**Architecture:** Generators are stateless Python modules in `packages/agent/src/suitest_agent/generators/` (the `agent` package houses both deterministic and LLM-driven generators for unified discovery; subdirectory split keeps boundaries clear). Classifier sniffs input via rule chain. Generation results stream via SSE to UI for live preview. Bundled MCP providers added under `packages/mcp/src/suitest_mcp/bundled/` (graphql, mongo, mysql in-process; kubernetes and grpc as subprocess wrappers). Custom MCP registration persists in `mcp_providers` table with encrypted secrets and discovery-time tool catalog. Code export uses templated codegen per target framework, with mixed-MCP step translation (e.g., postgres-mcp step → Playwright `test.beforeAll` hook with pg client).

**Tech Stack:** Python 3.12, FastAPI, packages/mcp + packages/agent, `openapi-pydantic` for OpenAPI parsing, `gql` + `httpx` for graphql-mcp, `motor` for mongo-mcp, `aiomysql` for mysql-mcp, `kubernetes_asyncio` for kubernetes-mcp, `grpcio` + `grpcio-tools` for grpc-mcp, `Faker` for crawler data, `playwright` for recorder (reuses M1c installation), `jinja2` for code export templates, SSE via FastAPI `StreamingResponse`, frontend Monaco diff viewer.

---

## Prerequisites

Before starting M2, verify:

- **M0** complete — monorepo, Docker compose, FastAPI + Vite boot, FastAPI-Users auth wired, base migrations applied, ZERO-tier `GET /capabilities` returning `{tier: "ZERO", autonomy: "manual", llm_provider: null}`.
- **M1a** complete — read-only REST endpoints, workspace scoping, audit log helper, pagination, error envelope, full seed (workspace `Nusantara Retail` + 1 project + 4 suites + 18 cases + 5 runs + 3 defects + 6 requirements + 8 integrations).
- **M1b** complete — read-only UI screens (Dashboard, Cases list/detail, Runs, Defects, Analytics, Traceability, Integrations grid, Docs) wired against M1a endpoints. `<Gated>` wrapper, `<TierBadge>`, `<McpProviderPill>`, `useCapabilities()` Zustand store all present.
- **M1c** complete — `packages/mcp` package: client, registry, pool, routing, invoker, health probe. 3 bundled providers (`playwright-mcp`, `api-http-mcp`, `postgres-mcp`) loaded into registry on startup with periodic health probe. `apps/runner` ARQ worker pulls run jobs, dispatches per-step to MCP via `step.mcp_provider`, streams logs to Redis pub/sub → WS, uploads artifacts to MinIO.
- **M1d** complete — Test case writes (POST/PATCH/DELETE), suite CRUD, drag-reorder steps, bulk operations, manual defect creation + rule-based auto-defect, Jira/Linear/GitHub adapters, Slack notifications, GitHub webhook trigger. `/test-cases` accepts `step.code` + `mcp_provider` + `target_kind`. `POST /test-cases/:id/run` enqueues ad-hoc run.
- DB has `mcp_providers`, `generator_runs`, `code_exports`, `recorder_sessions` tables placeholders. M1a created `mcp_providers` (used to register bundled providers at startup). `generator_runs`, `code_exports`, `recorder_sessions` may need a fresh Alembic migration as Task 0 of this plan if not already present (verify via `alembic heads`).

If any prerequisite is missing, stop and complete that milestone first.

---

## Conventions for this plan

- **TDD always.** Each backend task: (1) write failing pytest, (2) implement, (3) green test, (4) refactor. Each frontend task: vitest unit tests + Playwright E2E where flows are observable. Tests run in CI per task before commit.
- **Conventional commits per sub-step** with milestone reference: `feat(agent): add target classifier (Closes #M2-4)`, `feat(mcp): bundled graphql-mcp (Closes #M2-10)`, etc.
- **Pydantic v2** for all API I/O. Domain models in `packages/shared/suitest_shared/schemas/`. SQLAlchemy 2.0 async ORM in `packages/db/suitest_db/models/`.
- **mypy strict** with `disallow_untyped_defs=true`. No `Any` — use `TypedDict`, `Protocol`, generics. No `as any` in TypeScript.
- **No barrel files.** Direct imports only (`from suitest_agent.generators.classifier import classify` not `from suitest_agent.generators import classify`).
- **Capability gate** every endpoint declares `Depends(require_tier(...))`. All deterministic generators in this milestone declare `require_tier(Tier.ZERO | Tier.LOCAL | Tier.CLOUD)` because they work everywhere — but the dependency itself MUST be present so the gate is consistent and the future LLM-enrichment endpoints in M3 can be added by raising the floor.
- **Audit log** every mutation through `packages/db/audit.py::write_audit`. Generator runs, MCP provider registration, routing override, code exports all emit audit rows.
- **SSE format** strict per W3C spec — each event has `event: <name>\ndata: <json>\n\n`. Use FastAPI `StreamingResponse(generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})`. Heartbeat every 15s (`event: ping\ndata: {}\n\n`) to prevent intermediate proxies from idling out.
- **OpenTelemetry** spans wrap each generator (`generator.run` span, attrs: `source`, `target_kind`, `workspace_id`, `case_count`, `duration_ms`).
- **Workspace scoping** is mandatory — every service method takes `workspace_id` as first business parameter (after `user_id` if applicable). Cross-workspace access returns 404 (never 403, to avoid tenant enumeration).
- **Test fixtures** for OpenAPI specs live in `tests/fixtures/openapi/` (3 specs: `httpbin.json`, `petstore.json`, `custom-rate-limited.yaml`). Recorder fixtures in `tests/fixtures/recorder/`. Crawler fixtures in `tests/fixtures/crawler/` (5 static HTML pages served via testcontainer nginx). Code export fixtures in `tests/fixtures/cases/` (3 cases: `pure-fe.json`, `pure-be.json`, `mixed-mcp.json`).
- **Frontend mutations** use TanStack Query `useMutation` with optimistic snapshot + rollback. SSE consumed via native `EventSource` API.
- Each numbered task ends with a `git commit`. Some tasks have multiple sub-step commits — each sub-step commit is independent and CI-green.

---

## Task 0: Migration prep — `generator_runs`, `recorder_sessions`, `code_exports`

Verify the three new tables exist; if not, add a migration at the start.

- [ ] **0.1** Run `alembic heads` and `alembic history --indicate-current` to confirm current head. If `generator_runs` already exists from M1a, skip 0.2–0.4 for that table.
- [ ] **0.2** Create migration file `packages/db/suitest_db/migrations/versions/2026_05_26_m2_recorder_and_exports.py`:
  - `revision = "m2_recorder_and_exports"`
  - `down_revision = "<current head>"`
  - `upgrade()` creates:
    - `recorder_sessions(id text PK, workspace_id text FK→workspaces(id) ON DELETE CASCADE, user_id uuid FK→users(id) NULL, project_id text FK→projects(id), start_url text NOT NULL, mcp_provider text NOT NULL DEFAULT 'playwright-mcp', status text NOT NULL DEFAULT 'active', captured_events_json jsonb NOT NULL DEFAULT '[]'::jsonb, ws_room text NOT NULL, expires_at timestamptz NOT NULL, started_at timestamptz NOT NULL DEFAULT now(), finalized_at timestamptz NULL, finalized_case_id text NULL FK→test_cases(id))`
    - Index `ix_recorder_sessions_workspace_status` ON (workspace_id, status)
    - Index `ix_recorder_sessions_expires_at` ON (expires_at) WHERE status = 'active'
  - Confirm `generator_runs` table from M1a schema is present with shape from DATA_MODEL.md §4.4 (id, workspace_id, source, input_meta_json, output_case_ids_json, duration_ms, created_at, created_by_user_id). If missing, add to this same migration.
  - Confirm `code_exports` table from M1a schema is present with shape from DATA_MODEL.md §4.7 (id, case_id, target, exported_code_text, exported_at, user_id). If missing, add to this same migration.
  - `downgrade()` drops `recorder_sessions` and any tables added in upgrade.
- [ ] **0.3** Write pytest `packages/db/tests/test_migration_m2.py`:
  - Apply migration → verify each table exists via `inspector.get_table_names()`.
  - Verify indexes via `inspector.get_indexes("recorder_sessions")`.
  - Downgrade → tables removed.
- [ ] **0.4** `uv run alembic upgrade head` against dev DB; verify cleanly applies. `uv run pytest packages/db/tests/test_migration_m2.py -x` green.
- [ ] **0.5** Add SQLAlchemy ORM models for `RecorderSession`, and confirm/add `GeneratorRun` and `CodeExport` if not already present from M1a:
  - `packages/db/suitest_db/models/recorder_session.py`:
    ```python
    from __future__ import annotations
    from datetime import datetime
    import uuid
    from sqlalchemy import String, Text, ForeignKey, Index, DateTime, func
    from sqlalchemy.dialects.postgresql import JSONB, UUID
    from sqlalchemy.orm import Mapped, mapped_column
    from .base import Base, cuid

    class RecorderSession(Base):
        __tablename__ = "recorder_sessions"
        id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
        workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
        user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
        project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
        start_url: Mapped[str] = mapped_column(Text, nullable=False)
        mcp_provider: Mapped[str] = mapped_column(String(64), nullable=False, default="playwright-mcp")
        status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
        captured_events_json: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
        ws_room: Mapped[str] = mapped_column(String(120), nullable=False)
        expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
        started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
        finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
        finalized_case_id: Mapped[str | None] = mapped_column(ForeignKey("test_cases.id"))

        __table_args__ = (
            Index("ix_recorder_sessions_workspace_status", "workspace_id", "status"),
        )
    ```
  - Confirm `GeneratorRun` and `CodeExport` models exist in `packages/db/suitest_db/models/`. If missing, add them per DATA_MODEL.md §4.4 and §4.7.
- [ ] **0.6** Repository classes:
  - `packages/db/suitest_db/repositories/recorder_session_repo.py` — methods: `create`, `get_by_id`, `update_status`, `append_event`, `mark_finalized`, `list_active_expired`.
  - `packages/db/suitest_db/repositories/generator_run_repo.py` — methods: `create`, `get_by_id`, `list_by_workspace`.
  - `packages/db/suitest_db/repositories/code_export_repo.py` — methods: `create`, `list_by_case`.
- [ ] **0.7** Repository unit tests under `packages/db/tests/test_repos_m2.py`. Cover happy + cross-workspace 404 path for each method.
- [ ] **0.8** Commit: `feat(db): add recorder_sessions + verify generator_runs and code_exports tables (Closes #M2-2 #M2-12)`.

---

## Task 1: Target classifier — rule-based (`POST /generators/classify`)

The first piece. Every other generator endpoint consults this. Pure rules, no LLM.

### 1.1 Pydantic schemas

- [ ] **1.1.1** Create `packages/shared/suitest_shared/schemas/generator_input.py`:
  ```python
  from __future__ import annotations
  from enum import StrEnum
  from typing import Annotated, Literal
  from pydantic import BaseModel, ConfigDict, Field, HttpUrl

  class GenerationInputKind(StrEnum):
      URL = "url"
      FILE_CONTENT = "file_content"
      RAW_TEXT = "raw_text"

  class GenerationInput(BaseModel):
      model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)
      kind: GenerationInputKind
      value: Annotated[str, Field(min_length=1, max_length=2_000_000)]
      content_type_hint: str | None = None
      filename: str | None = None

  class RecommendedStrategy(StrEnum):
      OPENAPI_GENERATOR = "openapi-generator"
      URL_CRAWLER = "url-crawler"
      RECORDER = "recorder"
      URL_SEMANTIC = "url-semantic"        # requires LLM
      MCP_DISCOVERY = "mcp-discovery"      # requires LLM
      PRD_PARSING = "prd-parsing"          # requires LLM

  class TargetKind(StrEnum):
      BE_REST = "BE_REST"
      BE_GRAPHQL = "BE_GRAPHQL"
      BE_GRPC = "BE_GRPC"
      FE_WEB = "FE_WEB"
      FE_MOBILE = "FE_MOBILE"
      DATA = "DATA"
      INFRA = "INFRA"
      MIXED = "MIXED"
      CUSTOM = "CUSTOM"

  class RecommendedMcp(BaseModel):
      model_config = ConfigDict(from_attributes=True)
      id: str | None = None       # null if no registered provider matches
      name: str                    # e.g. "api-http-mcp"

  class StrategyAlternative(BaseModel):
      strategy: RecommendedStrategy
      requires_tier: Literal["ZERO", "LOCAL", "CLOUD"]

  class ClassificationResult(BaseModel):
      model_config = ConfigDict(from_attributes=True)
      target_kind: TargetKind
      confidence: Annotated[float, Field(ge=0.0, le=1.0)]
      recommended_mcp: RecommendedMcp
      recommended_strategy: RecommendedStrategy
      alternatives: list[StrategyAlternative] = Field(default_factory=list)
      rationale: str
  ```
- [ ] **1.1.2** Confirm `TargetKind` is the single source of truth — `packages/shared/suitest_shared/schemas/enums.py` may re-export from here. No duplicate definition.

### 1.2 Classifier module

- [ ] **1.2.1** Create `packages/agent/src/suitest_agent/generators/__init__.py` (empty docstring only — no exports).
- [ ] **1.2.2** Create `packages/agent/src/suitest_agent/generators/classifier.py`:
  ```python
  from __future__ import annotations
  import json
  import re
  from typing import Final
  from urllib.parse import urlparse
  from suitest_shared.schemas.generator_input import (
      ClassificationResult, GenerationInput, GenerationInputKind,
      RecommendedMcp, RecommendedStrategy, StrategyAlternative, TargetKind,
  )

  _OPENAPI_URL_RE: Final = re.compile(r"/(openapi|swagger)(\.json|\.yaml|\.yml)$", re.I)
  _GRAPHQL_URL_TOKENS: Final = ("graphql", "/gql")
  _K8S_KIND_RE: Final = re.compile(
      r"^kind:\s*(Deployment|Service|StatefulSet|DaemonSet|Ingress|ConfigMap|Job|CronJob)\b",
      re.M,
  )

  def classify(inp: GenerationInput) -> ClassificationResult:
      """Rule-based classifier; first match wins."""
      # URL-based signals
      if inp.kind == GenerationInputKind.URL:
          parsed = urlparse(inp.value)
          path_lower = parsed.path.lower()
          if _OPENAPI_URL_RE.search(path_lower):
              return _be_rest("URL ends in openapi|swagger spec path")
          if any(t in inp.value.lower() for t in _GRAPHQL_URL_TOKENS):
              return _be_graphql("URL contains graphql token")
          if parsed.scheme in {"postgresql", "mysql", "mongodb"}:
              return _data(parsed.scheme, "DB connection URL scheme")
          if parsed.scheme in {"http", "https"}:
              return _fe_web("Generic HTTP(S) URL — assume web UI")
      # Filename signals (file content kind)
      if inp.kind == GenerationInputKind.FILE_CONTENT and inp.filename:
          low = inp.filename.lower()
          if low.endswith(".graphql"):
              return _be_graphql("Filename ends in .graphql")
          if low.endswith(".proto"):
              return _be_grpc("Filename ends in .proto")
          if low.endswith((".apk", ".ipa")):
              return _fe_mobile("Mobile binary file extension")
      # Body content signals (file_content or raw_text)
      if inp.kind in {GenerationInputKind.FILE_CONTENT, GenerationInputKind.RAW_TEXT}:
          body = inp.value
          try:
              j = json.loads(body)
              if isinstance(j, dict):
                  if "openapi" in j or "swagger" in j:
                      return _be_rest("JSON body has openapi/swagger field")
                  if j.get("kind") == "Service" and "spec" in j:
                      return _infra("JSON body kind=Service with spec")
          except (ValueError, json.JSONDecodeError):
              pass
          if _K8S_KIND_RE.search(body):
              return _infra("YAML kind: Deployment/Service/...")
      # Content-type signals
      if inp.content_type_hint:
          ct = inp.content_type_hint.lower()
          if ct.startswith("text/html"):
              return _fe_web("Content-Type text/html")
          if ct.startswith(("text/markdown", "text/plain")):
              return _mixed("Free-form text — likely PRD")
      return _custom("No rule matched")

  def _be_rest(rationale: str) -> ClassificationResult:
      return ClassificationResult(
          target_kind=TargetKind.BE_REST,
          confidence=0.95,
          recommended_mcp=RecommendedMcp(name="api-http-mcp"),
          recommended_strategy=RecommendedStrategy.OPENAPI_GENERATOR,
          alternatives=[
              StrategyAlternative(strategy=RecommendedStrategy.PRD_PARSING, requires_tier="CLOUD"),
          ],
          rationale=rationale,
      )

  def _be_graphql(rationale: str) -> ClassificationResult:
      return ClassificationResult(
          target_kind=TargetKind.BE_GRAPHQL,
          confidence=0.9,
          recommended_mcp=RecommendedMcp(name="graphql-mcp"),
          recommended_strategy=RecommendedStrategy.OPENAPI_GENERATOR,
          alternatives=[],
          rationale=rationale,
      )

  def _be_grpc(rationale: str) -> ClassificationResult:
      return ClassificationResult(
          target_kind=TargetKind.BE_GRPC,
          confidence=0.9,
          recommended_mcp=RecommendedMcp(name="grpc-mcp"),
          recommended_strategy=RecommendedStrategy.OPENAPI_GENERATOR,
          alternatives=[],
          rationale=rationale,
      )

  def _fe_web(rationale: str) -> ClassificationResult:
      return ClassificationResult(
          target_kind=TargetKind.FE_WEB,
          confidence=0.7,
          recommended_mcp=RecommendedMcp(name="playwright-mcp"),
          recommended_strategy=RecommendedStrategy.URL_CRAWLER,
          alternatives=[
              StrategyAlternative(strategy=RecommendedStrategy.RECORDER, requires_tier="ZERO"),
              StrategyAlternative(strategy=RecommendedStrategy.URL_SEMANTIC, requires_tier="CLOUD"),
          ],
          rationale=rationale,
      )

  def _fe_mobile(rationale: str) -> ClassificationResult:
      return ClassificationResult(
          target_kind=TargetKind.FE_MOBILE,
          confidence=0.95,
          recommended_mcp=RecommendedMcp(name="appium-mcp"),
          recommended_strategy=RecommendedStrategy.URL_CRAWLER,
          alternatives=[],
          rationale=rationale,
      )

  def _data(scheme: str, rationale: str) -> ClassificationResult:
      provider = {"postgresql": "postgres-mcp", "mysql": "mysql-mcp", "mongodb": "mongo-mcp"}[scheme]
      return ClassificationResult(
          target_kind=TargetKind.DATA,
          confidence=0.95,
          recommended_mcp=RecommendedMcp(name=provider),
          recommended_strategy=RecommendedStrategy.OPENAPI_GENERATOR,
          alternatives=[],
          rationale=rationale,
      )

  def _infra(rationale: str) -> ClassificationResult:
      return ClassificationResult(
          target_kind=TargetKind.INFRA,
          confidence=0.85,
          recommended_mcp=RecommendedMcp(name="kubernetes-mcp"),
          recommended_strategy=RecommendedStrategy.OPENAPI_GENERATOR,
          alternatives=[],
          rationale=rationale,
      )

  def _mixed(rationale: str) -> ClassificationResult:
      return ClassificationResult(
          target_kind=TargetKind.MIXED,
          confidence=0.6,
          recommended_mcp=RecommendedMcp(name="playwright-mcp"),
          recommended_strategy=RecommendedStrategy.PRD_PARSING,
          alternatives=[
              StrategyAlternative(strategy=RecommendedStrategy.RECORDER, requires_tier="ZERO"),
          ],
          rationale=rationale,
      )

  def _custom(rationale: str) -> ClassificationResult:
      return ClassificationResult(
          target_kind=TargetKind.CUSTOM,
          confidence=0.3,
          recommended_mcp=RecommendedMcp(name="playwright-mcp"),
          recommended_strategy=RecommendedStrategy.RECORDER,
          alternatives=[],
          rationale=rationale,
      )
  ```
- [ ] **1.2.3** Pytest `packages/agent/tests/test_classifier.py` — cover every branch:
  - `test_openapi_json_url` — input URL `https://api.example.com/openapi.json` → `BE_REST`, strategy `openapi-generator`, mcp `api-http-mcp`.
  - `test_openapi_yaml_url` — `.../openapi.yaml` → `BE_REST`.
  - `test_swagger_json_url` — `.../swagger.json` → `BE_REST`.
  - `test_graphql_url_contains_token` — `https://api.example.com/graphql` → `BE_GRAPHQL`, mcp `graphql-mcp`.
  - `test_graphql_filename` — file with `.graphql` extension → `BE_GRAPHQL`.
  - `test_proto_filename` → `BE_GRPC`, mcp `grpc-mcp`.
  - `test_apk_filename` → `FE_MOBILE`.
  - `test_ipa_filename` → `FE_MOBILE`.
  - `test_postgres_url` — `postgresql://u:p@host/db` → `DATA`, mcp `postgres-mcp`.
  - `test_mysql_url` → `DATA`, mcp `mysql-mcp`.
  - `test_mongodb_url` → `DATA`, mcp `mongo-mcp`.
  - `test_openapi_body_json` — raw text with `{"openapi": "3.0.0", "paths": {...}}` → `BE_REST`.
  - `test_swagger_body_json` — `{"swagger": "2.0"}` → `BE_REST`.
  - `test_k8s_yaml_deployment` — body starts with `kind: Deployment\n...` → `INFRA`.
  - `test_k8s_yaml_service` → `INFRA`.
  - `test_text_html_content_type` → `FE_WEB`.
  - `test_text_markdown_content_type` → `MIXED`, strategy `prd-parsing`.
  - `test_text_plain_content_type` → `MIXED`.
  - `test_generic_https_url_falls_through_to_fe_web` — `https://example.com/app` no openapi tokens → `FE_WEB`, strategy `url-crawler`.
  - `test_unmatched_returns_custom` — empty raw text with no hints → `CUSTOM`, low confidence.
  - `test_confidence_bounds` — every branch returns `0.0 ≤ confidence ≤ 1.0`.
  - `test_rationale_non_empty` — every branch has non-empty rationale string.
- [ ] **1.2.4** Run `uv run pytest packages/agent/tests/test_classifier.py -x`. Green.
- [ ] **1.2.5** mypy clean: `uv run mypy packages/agent/src/suitest_agent/generators/classifier.py`.
- [ ] **1.2.6** Commit: `feat(agent): rule-based target classifier (Closes #M2-4)`.

### 1.3 API router scaffold + classify endpoint

- [ ] **1.3.1** Create `apps/api/src/suitest_api/routers/generators.py` (this router will host all M2 endpoints):
  ```python
  from __future__ import annotations
  from typing import Annotated
  from fastapi import APIRouter, Depends
  from suitest_agent.generators.classifier import classify
  from suitest_shared.schemas.generator_input import ClassificationResult, GenerationInput
  from suitest_api.deps.auth import RequestContext, require_role
  from suitest_api.deps.tier import require_tier
  from suitest_core.capabilities import Tier
  from suitest_db.repositories.mcp_provider_repo import McpProviderRepo

  router = APIRouter(prefix="/generators", tags=["generators"])

  @router.post("/classify", response_model=ClassificationResult)
  async def classify_input(
      payload: GenerationInput,
      ctx: Annotated[RequestContext, Depends(require_role({"QA", "ADMIN", "OWNER"}))],
      _: None = Depends(require_tier(Tier.ZERO | Tier.LOCAL | Tier.CLOUD)),
      mcp_repo: McpProviderRepo = Depends(),
  ) -> ClassificationResult:
      result = classify(payload)
      # Resolve recommended_mcp.id by name within this workspace
      provider = await mcp_repo.find_by_name(ctx.workspace_id, result.recommended_mcp.name)
      if provider:
          result.recommended_mcp.id = provider.id
      return result
  ```
- [ ] **1.3.2** Register the router in `apps/api/src/suitest_api/main.py`: `app.include_router(generators.router, prefix="/api/v1")`.
- [ ] **1.3.3** Pytest `apps/api/tests/test_generators_classify.py`:
  - `test_classify_openapi_url_authenticated` → 200 + correct shape + `recommended_mcp.id` resolved if `api-http-mcp` registered, else `id=None` + `name="api-http-mcp"`.
  - `test_classify_unauthenticated` → 401.
  - `test_classify_viewer_role_forbidden` → 403.
  - `test_classify_cross_workspace_provider_resolution` — register `api-http-mcp` in workspace A only; classify as user from workspace B → `id=None` (no cross-tenant leak).
  - `test_classify_validation_error` — empty `value` field → 422.
- [ ] **1.3.4** Run tests. Green.
- [ ] **1.3.5** Commit: `feat(api): POST /generators/classify endpoint (Closes #M2-4)`.

---

## Task 2: OpenAPI generator (`POST /generators/openapi`)

Deterministic OpenAPI → per-operation contract suite. Targets `api-http-mcp`.

### 2.1 Dependencies

- [ ] **2.1.1** Add to `packages/agent/pyproject.toml`:
  - `openapi-pydantic >= 0.4.0`
  - `jsonschema >= 4.21`
  - `faker >= 25.0`
  - `httpx >= 0.27` (already there)
- [ ] **2.1.2** `uv sync` — verify install.

### 2.2 Pydantic schemas

- [ ] **2.2.1** Append to `packages/shared/suitest_shared/schemas/generator_input.py`:
  ```python
  class OpenApiGeneratorOptions(BaseModel):
      model_config = ConfigDict(str_strip_whitespace=True)
      include_negative_auth: bool = True
      include_schema_validation: bool = True
      include_required_field_tests: bool = True
      include_boundary_tests: bool = True
      include_rate_limit_tests: bool = True
      tag_prefix: str | None = None
      tags_filter: list[str] = Field(default_factory=list)
      auth_profile_id: str | None = None
      max_cases_per_operation: int = 20
      base_url_override: str | None = None

  class OpenApiGenerateRequest(BaseModel):
      model_config = ConfigDict(str_strip_whitespace=True)
      target_suite_id: str
      spec_url: str | None = None
      spec_content: str | None = None
      options: OpenApiGeneratorOptions = Field(default_factory=OpenApiGeneratorOptions)

  class TestStepDraft(BaseModel):
      order: int
      action: str
      expected: str
      code: str
      mcp_provider: str
      target_kind: TargetKind
      data: dict[str, object] | None = None

  class TestCaseDraft(BaseModel):
      name: str
      description: str
      priority: Literal["P0", "P1", "P2", "P3"] = "P2"
      source: Literal["MANUAL", "MCP", "AI", "RECORDER", "HEURISTIC_CRAWL", "IMPORT"]
      target_kind: TargetKind
      tags: list[str] = Field(default_factory=list)
      generated_from: dict[str, object] = Field(default_factory=dict)
      steps: list[TestStepDraft]

  class GeneratorRunResponse(BaseModel):
      generator_run_id: str
      target_suite_id: str
      cases_created: int
      public_ids: list[str]
      duration_ms: int
  ```

### 2.3 OpenAPI generator module

- [ ] **2.3.1** Create `packages/agent/src/suitest_agent/generators/openapi_generator.py`:
  - `class OpenApiGenerator`:
    - `__init__(self, http_client: httpx.AsyncClient, options: OpenApiGeneratorOptions)`.
    - `async def fetch_spec(self, spec_url: str | None, spec_content: str | None) -> openapi_pydantic.OpenAPI`. Raise `OpenApiSpecError` on parse failure.
    - `async def generate(self) -> AsyncIterator[TestCaseDraft]`. Per spec.paths.*.{get,post,put,patch,delete}: yield case drafts via async generator (for SSE consumption).
  - Algorithm per operation `op`:
    1. **contract_test** (always): one happy case. Build request body via `_build_example_body(op)` (uses schema `example`/`examples` first, falls back to Faker by JSON schema type). Build query/path params similarly. Step.code is a single `mcp.api.request(...)` call with `assert response.status == expected_status` and optional `assert validate_jsonschema(response.body, schema)` when `options.include_schema_validation` and the response defines a schema.
    2. **auth_negative_test** if `op.security or spec.security`: 2 cases — missing token (no Authorization header) and invalid token (`Bearer xxxx`). Expect `status in {401, 403}`.
    3. **required_field_tests** if `options.include_required_field_tests` and op has request body schema with `required` fields: one case per required field, omitting just that field. Expect 4xx.
    4. **boundary_tests** if `options.include_boundary_tests` and schema fields have `minimum/maximum/minLength/maxLength`: for int → min-1 and max+1; for string → empty if minLength≥1 and `'x'*(maxLength+1)`. Expect 4xx.
    5. **rate_limit_test** if `options.include_rate_limit_tests` and any response defines `x-ratelimit-*` header or `429` status: one case that issues `limit+1` requests, expects 429 after threshold.
  - Cap output per operation at `options.max_cases_per_operation`.
  - Each `TestCaseDraft` has:
    - `name = f"{op_method.upper()} {op_path} — {case_kind}"`
    - `target_kind = TargetKind.BE_REST`
    - `source = "MCP"` (matches existing enum; deterministic generation tags via `generated_from`)
    - `generated_from = {"source": "OPENAPI", "operation_id": op.operationId, "path": op_path, "method": op_method, "case_kind": case_kind, "spec_url": spec_url}`
    - `tags = ["api-contract", op_path.split('/')[1] if '/' in op_path else "api"]` plus `options.tag_prefix` prepended if set
    - `steps = [TestStepDraft(order=1, action=..., expected=..., code=<rendered mcp.api.request>, mcp_provider="api-http-mcp", target_kind=BE_REST)]`. Multi-step cases for rate-limit case: N steps for N requests.
- [ ] **2.3.2** Helper `_build_example_body(schema: dict, faker: Faker) -> object`:
  - If `example` set → return it.
  - If `examples` set → return first.
  - Else recurse by `type` field. `string` with `format=email` → `faker.email()`; `format=date-time` → ISO timestamp; `format=uuid` → UUID4. `integer` → `faker.random_int(min=0, max=100)`; respect `minimum`/`maximum`. `boolean` → True. `array` → list of one item from inner schema. `object` → dict from `properties` recursively (include all `required` keys).
- [ ] **2.3.3** Helper `_render_request_code(method, url, headers, body, expected_status, response_schema_ref, options) -> str` — emits literal Python that the runner can `exec` against the api-http-mcp tool:
  ```
  response = await mcp.api.request(
      method="POST",
      url="{base_url}/users",
      headers={"Content-Type": "application/json", "Authorization": "Bearer {{auth.token}}"},
      body={"email": "test+{{uuid}}@example.com", "name": "Test User"},
  )
  assert response.status == 201, f"Expected 201, got {response.status}"
  assert validate_jsonschema(response.body, User_schema)
  ```
  Use double-curly Jinja-style placeholders that runner resolves at runtime (already supported in M1c).

### 2.4 Service + endpoint

- [ ] **2.4.1** Create `apps/api/src/suitest_api/services/generator_service.py`:
  - `class GeneratorService`:
    - `__init__(self, db_session, generator_run_repo, case_repo, audit, http_client)`.
    - `async def run_openapi(self, workspace_id, user_id, request: OpenApiGenerateRequest) -> AsyncIterator[GeneratorSseEvent]`. Yields SSE-shaped events: `progress`, `case`, `complete`, `error`.
    - Inside: start OTel span `generator.openapi`; create `GeneratorRun` row with `source="openapi"`; instantiate `OpenApiGenerator`; iterate cases; for each, persist as `TestCase` row with `status=DRAFT`, link to `target_suite_id`; append `public_id` to `output_case_ids_json`. On completion update duration_ms + commit row + audit `generator.openapi.completed`.
- [ ] **2.4.2** Append to `apps/api/src/suitest_api/routers/generators.py`:
  ```python
  @router.post("/openapi")
  async def generate_openapi(
      payload: OpenApiGenerateRequest,
      ctx: Annotated[RequestContext, Depends(require_role({"QA", "ADMIN", "OWNER"}))],
      _: None = Depends(require_tier(Tier.ZERO | Tier.LOCAL | Tier.CLOUD)),
      svc: GeneratorService = Depends(),
  ) -> StreamingResponse:
      async def stream() -> AsyncIterator[bytes]:
          async for event in svc.run_openapi(ctx.workspace_id, ctx.user_id, payload):
              yield _format_sse(event).encode()
      return StreamingResponse(
          stream(),
          media_type="text/event-stream",
          headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
      )
  ```
  Define `_format_sse(event: GeneratorSseEvent) -> str` returning `f"event: {event.kind}\ndata: {event.json()}\n\n"`. Heartbeat every 15s emitted via a `asyncio.timeout` race against the next event.

### 2.5 Tests

- [ ] **2.5.1** Add 3 fixture specs to `apps/api/tests/fixtures/openapi/`:
  - `httpbin.json` — copy of public httpbin OpenAPI spec (small, ~10 operations).
  - `petstore.json` — official Petstore 3.0 spec.
  - `custom-rate-limited.yaml` — small custom spec with `x-ratelimit-*` headers documented to exercise the rate-limit branch.
- [ ] **2.5.2** Pytest `apps/api/tests/test_generators_openapi.py`:
  - `test_generate_from_petstore_spec_content` — POST with `spec_content`, count cases per category, assert ≥ 1 contract test per operation, schema-validate each `step.code` against allowed Python source pattern (no `eval`, no `__import__`).
  - `test_generate_from_httpbin_spec_url` — POST with `spec_url` (httpx mocked to return local fixture); assert duration_ms recorded, `cases_created > 0`.
  - `test_generate_with_options_disabled` — turn off `include_negative_auth`/`include_required_field_tests`/`include_boundary_tests` → fewer cases generated.
  - `test_generate_rate_limit_case_present_when_documented` — custom-rate-limited.yaml → at least 1 case with `case_kind=rate_limit`.
  - `test_generate_persists_generator_run_row` — verify row exists in DB after stream completes, with correct `output_case_ids_json`.
  - `test_generate_cases_persist_as_draft` — assert TestCase rows have `status=DRAFT`.
  - `test_generate_tags_filter` — only include operations under tag "pets" → fewer cases.
  - `test_generate_invalid_spec_returns_error_event` — malformed JSON → SSE stream emits `event: error` with structured payload, then closes.
  - `test_generate_sse_format_strict` — parse the response body line-by-line, ensure each `event:` is followed by `data:` JSON and double-newline terminator.
  - `test_generate_unauthenticated_returns_401` — no auth header.
  - `test_generate_unknown_suite_returns_404` — `target_suite_id` not in workspace → 404 `RESOURCE_NOT_FOUND`.
- [ ] **2.5.3** Run tests. Green.
- [ ] **2.5.4** Commit: `feat(agent): deterministic OpenAPI generator + endpoint (Closes #M2-1)`.

---

## Task 3: Heuristic URL crawler (`POST /generators/crawler`)

BFS depth-N from start URL, fill forms with Faker, emit skeleton cases.

### 3.1 Pydantic schemas

- [ ] **3.1.1** Append to `packages/shared/suitest_shared/schemas/generator_input.py`:
  ```python
  class CrawlerAuthConfig(BaseModel):
      kind: Literal["none", "cookie", "bearer", "form"] = "none"
      login_url: str | None = None
      cookie: str | None = None
      token: str | None = None
      credentials: dict[str, str] | None = None

  class CrawlerOptions(BaseModel):
      max_depth: int = Field(default=2, ge=1, le=5)
      max_pages: int = Field(default=20, ge=1, le=200)
      same_origin_only: bool = True
      faker_locale: str = "en_US"
      tag_prefix: str | None = None
      include_form_cases: bool = True

  class CrawlerGenerateRequest(BaseModel):
      target_suite_id: str
      start_url: str
      auth: CrawlerAuthConfig = Field(default_factory=CrawlerAuthConfig)
      options: CrawlerOptions = Field(default_factory=CrawlerOptions)
  ```

### 3.2 Crawler module

- [ ] **3.2.1** Create `packages/agent/src/suitest_agent/generators/url_crawler.py`:
  - `class UrlCrawler`:
    - `__init__(self, mcp_invoker: McpInvoker, options: CrawlerOptions, auth: CrawlerAuthConfig)`.
    - `async def crawl(self, start_url: str, workspace_id: str) -> AsyncIterator[TestCaseDraft]`.
  - Algorithm (BFS):
    1. `queue = [(start_url, 0)]; visited = set(); origin = urlparse(start_url).hostname`.
    2. While queue and `len(visited) < options.max_pages`:
       - Pop `(url, depth)`. If visited or `depth > options.max_depth` continue. Mark visited.
       - Invoke `mcp_invoker.invoke("playwright-mcp", "browser.navigate", {"url": url, "wait_until": "networkidle"})`.
       - Capture console: `console = await mcp_invoker.invoke("playwright-mcp", "browser.get_console_log", {})`.
       - Emit smoke case: 2 steps (navigate, assert no console error). `target_kind=FE_WEB`, `mcp_provider="playwright-mcp"`.
       - Eval DOM via `mcp.browser.eval` to enumerate forms + interactive elements + same-origin links:
         ```javascript
         (() => ({
            forms: [...document.querySelectorAll('form')].map(f => ({
              id: f.id || null,
              action: f.action || null,
              method: f.method,
              fields: [...f.querySelectorAll('input, textarea, select')].map(el => ({
                name: el.name, type: el.type || el.tagName.toLowerCase(),
                selector: el.id ? '#' + el.id : `[name="${el.name}"]`,
                required: el.required, placeholder: el.placeholder,
              })),
              submit_selector: f.querySelector('[type=submit]')?.id ? '#' + f.querySelector('[type=submit]').id : 'form button[type=submit]'
            })),
            links: [...document.querySelectorAll('a[href]')].map(a => a.href),
         }))()
         ```
       - If `options.include_form_cases`, for each form: emit form case with steps (navigate → fill each field with Faker per type → submit → wait for navigation OR success indicator).
       - Same-origin link discovery: filter links by hostname (if `options.same_origin_only`), enqueue at `depth+1`.
  - Faker integration: `_fake_for_field(field_type: str, faker: Faker) -> str`:
    - email → `faker.email()`; password → `faker.password(length=12)`; tel → `faker.phone_number()`; text → `faker.sentence(nb_words=3)`; number → str(faker.random_int(1, 100)); date → `faker.date()`; url → `faker.url()`; default → `faker.word()`.

### 3.3 Endpoint + service

- [ ] **3.3.1** Append to `GeneratorService` an `async def run_crawler(workspace_id, user_id, request: CrawlerGenerateRequest) -> AsyncIterator[GeneratorSseEvent]` that mirrors `run_openapi` (OTel span, generator_run row, persist cases as DRAFT). Inject `McpInvoker` to drive `playwright-mcp`.
- [ ] **3.3.2** Append router handler `POST /generators/crawler` with same `StreamingResponse` pattern.

### 3.4 Tests

- [ ] **3.4.1** Add fixture under `apps/api/tests/fixtures/crawler/site/`:
  - `index.html` — 3 links + 1 contact form (name, email, message).
  - `about.html` — content + 1 link back to index.
  - `products.html` — product cards with details links.
  - `contact.html` — duplicate of contact form for variety.
  - `login.html` — login form (email + password).
- [ ] **3.4.2** Pytest `apps/api/tests/test_generators_crawler.py`:
  - Use `testcontainers.nginx.NginxContainer` (or `python:3.12-slim` running `python -m http.server` mounted with the fixture) to serve the 5-page site.
  - `test_crawl_emits_smoke_case_per_page` — depth=2, max_pages=10 → at least 5 smoke cases.
  - `test_crawl_emits_form_cases_when_enabled` — assert ≥ 2 form cases (contact + login forms).
  - `test_crawl_no_form_cases_when_disabled` — `include_form_cases=False` → only smoke cases.
  - `test_crawl_respects_max_depth` — `max_depth=1` from index → does not crawl pages 2 levels deep (asserted by visited count).
  - `test_crawl_respects_max_pages` — `max_pages=3` → exactly 3 smoke cases.
  - `test_crawl_same_origin_filter` — include external `<a href="https://example.com">` → not enqueued.
  - `test_crawl_persists_generator_run` — row created.
  - `test_crawl_uses_playwright_mcp` — mock `mcp_invoker.invoke`, assert each step references `playwright-mcp`.
- [ ] **3.4.3** Run tests. Green.
- [ ] **3.4.4** Commit: `feat(agent): heuristic URL crawler generator (Closes #M2-3)`.

---

## Task 4: Browser Recorder backend

Live recording session via Playwright MCP. WS streams events; `/finalize` emits a TestCase.

### 4.1 Pydantic schemas

- [ ] **4.1.1** Append to `packages/shared/suitest_shared/schemas/generator_input.py`:
  ```python
  class RecorderSessionStartRequest(BaseModel):
      project_id: str
      start_url: str
      mcp_provider: str = "playwright-mcp"

  class RecorderSessionStartResponse(BaseModel):
      session_id: str
      ws_room: str
      browser_url: str | None = None
      expires_at: datetime

  class RecorderEventKind(StrEnum):
      NAVIGATE = "navigate"
      CLICK = "click"
      TYPE = "type"
      ASSERT = "assert"
      NETWORK = "network"

  class RecorderEvent(BaseModel):
      kind: RecorderEventKind
      timestamp: datetime
      url: str | None = None
      selector: str | None = None
      text: str | None = None
      masked: bool = False
      assertion: dict[str, object] | None = None
      network: dict[str, object] | None = None

  class RecorderFinalizeRequest(BaseModel):
      target_suite_id: str
      name: str
      priority: Literal["P0", "P1", "P2", "P3"] = "P2"
      description: str | None = None
  ```

### 4.2 Session manager

- [ ] **4.2.1** Create `packages/agent/src/suitest_agent/generators/recorder.py`:
  - `class RecorderSessionManager`:
    - `__init__(self, mcp_invoker, recorder_repo, redis, ttl_minutes: int = 30)`.
    - `async def start(workspace_id, user_id, request) -> RecorderSession`:
      - Create `RecorderSession` row, status=`active`, ws_room=`recorder:{id}`, expires_at=`now+ttl`.
      - Invoke `playwright-mcp` `browser.start_recording` tool with `{session_id, start_url}`. MCP returns optional `browser_url` (DevTools preview).
      - Return session.
    - `async def append_event(session_id, event: RecorderEvent)`:
      - Load session; assert status=`active` else raise `RecorderSessionExpired`.
      - Append event to `captured_events_json` (atomic update).
      - Publish to Redis pub/sub channel `recorder:{session_id}` for WS subscribers.
    - `async def finalize(session_id, workspace_id, user_id, request) -> TestCaseDraft`:
      - Load session; assert status=`active` else 410.
      - Invoke `playwright-mcp` `browser.stop_recording` tool with `{session_id}` → returns final trace events.
      - Merge stored events with trace.
      - `_convert_events_to_case(events, request) -> TestCaseDraft`:
        - One step per `navigate`/`click`/`type`/`assert`.
        - Mask any `type` event flagged `masked=True` (e.g. password fields): replace `text` with `{{password}}` placeholder.
        - Network events with `4xx`/`5xx` status → emit auto-assertion step `assert response.status == <observed_status>`.
      - Persist as `TestCase` with `source="RECORDER"`, `generated_from={"source": "RECORDER", "session_id": session_id, "start_url": session.start_url}`, status=DRAFT.
      - Mark session `status="finalized"`, `finalized_at=now`, `finalized_case_id=<new_case_id>`.
      - Return draft.
    - Background task `async def expire_idle_sessions()`:
      - Every 60s: load sessions where `status="active" AND expires_at < now`. For each: invoke `browser.stop_recording`, mark `status="expired"`.
- [ ] **4.2.2** Define exceptions `RecorderSessionExpired`, `RecorderSessionNotFound`. Map to 410 Gone and 404 respectively in `errors.py`.

### 4.3 Endpoints

- [ ] **4.3.1** Append to `apps/api/src/suitest_api/routers/generators.py`:
  ```python
  @router.post("/recorder/sessions", response_model=RecorderSessionStartResponse)
  async def start_recorder_session(...)

  @router.post("/recorder/sessions/{session_id}/finalize", response_model=TestCaseRead)
  async def finalize_recorder_session(...)

  @router.delete("/recorder/sessions/{session_id}")
  async def cancel_recorder_session(...)
  ```
- [ ] **4.3.2** WebSocket handler in `apps/api/src/suitest_api/routers/ws.py` (existing from M1c, extend):
  - Add room handler for `subscribe.recorder` event:
    - Validate session belongs to caller's workspace.
    - Subscribe to Redis channel `recorder:{session_id}`.
    - Forward each event to client as `{"type": "generator.recorder.step", "data": {...}}`.

### 4.4 Tests (integration)

- [ ] **4.4.1** Add `apps/api/tests/test_recorder_session.py`:
  - Fixture: testcontainer nginx serving 1 simple page with a login form.
  - Mock `playwright-mcp` `browser.start_recording` to return immediately; mock `browser.stop_recording` to return synthetic event trace (navigate → type email → type password → click submit → navigate to /dashboard).
  - `test_start_session_creates_row` — POST `/generators/recorder/sessions` → 200 + session_id + ws_room. Row in DB with status=active.
  - `test_append_event_persists` — invoke `RecorderSessionManager.append_event` directly with 3 events; reload; assert `captured_events_json` length=3.
  - `test_finalize_emits_case_with_steps_per_event` — start → append 4 events → finalize → response is `TestCaseRead` with 4 steps (1 per event), `source="RECORDER"`.
  - `test_finalize_masks_password_field` — type event on `<input type="password">` flagged `masked=True` → step.code contains `{{password}}` not raw password.
  - `test_finalize_after_expired_returns_410` — manually set `expires_at` in past → finalize → 410 Gone.
  - `test_double_finalize_returns_410` — finalize once → finalize again → 410.
  - `test_cancel_session_marks_cancelled` — DELETE → status=cancelled.
  - `test_cross_workspace_session_returns_404` — workspace B finalizes workspace A's session → 404 (not 403).
  - `test_expire_idle_sessions_background` — create 2 sessions, 1 expired; run task; assert expired one marked status=expired, browser.stop_recording invoked.
- [ ] **4.4.2** Run tests. Green.
- [ ] **4.4.3** Commit: `feat(agent): browser recorder session + finalize (Closes #M2-2)`.

---

## Task 5: Bundled MCP — graphql-mcp

In-process MCP server using `gql` + `httpx`.

### 5.1 Dependencies

- [ ] **5.1.1** Add to `packages/mcp/pyproject.toml`:
  - `gql[all] >= 3.5.0`
  - (httpx already there from M1c)

### 5.2 Provider module

- [ ] **5.2.1** Create `packages/mcp/src/suitest_mcp/bundled/graphql.py`:
  ```python
  from __future__ import annotations
  from typing import Any
  import httpx
  from gql import Client, gql
  from gql.transport.httpx import HTTPXAsyncTransport
  from suitest_mcp.bundled.base import BundledProvider, ToolDefinition
  from suitest_mcp.models import McpToolResult

  class GraphQlProvider(BundledProvider):
      name = "graphql-mcp"
      kind = "graphql"
      tools: list[ToolDefinition] = [
          ToolDefinition(name="introspect", input_schema={"type": "object", "properties": {}, "additionalProperties": False}),
          ToolDefinition(name="query", input_schema={
              "type": "object",
              "required": ["query"],
              "properties": {
                  "query": {"type": "string"},
                  "variables": {"type": "object"},
                  "operation_name": {"type": "string"},
              },
              "additionalProperties": False,
          }),
          ToolDefinition(name="mutation", input_schema={"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}, "variables": {"type": "object"}}}),
          ToolDefinition(name="assert_field_value", input_schema={"type": "object", "required": ["response", "json_path", "expected"], "properties": {"response": {"type": "object"}, "json_path": {"type": "string"}, "expected": {}}}),
          ToolDefinition(name="assert_no_errors", input_schema={"type": "object", "required": ["response"], "properties": {"response": {"type": "object"}}}),
      ]

      async def health(self) -> bool:
          # Connectivity probe: GET on endpoint without query (most GraphQL servers respond 400 or 200 to a bare request).
          try:
              async with httpx.AsyncClient(timeout=5.0) as c:
                  r = await c.get(self.config["endpoint"])
                  return r.status_code < 500
          except Exception:
              return False

      async def invoke(self, tool: str, args: dict[str, Any]) -> McpToolResult:
          if tool == "introspect":
              return await self._introspect()
          if tool == "query" or tool == "mutation":
              return await self._exec(args["query"], args.get("variables"), args.get("operation_name"))
          if tool == "assert_field_value":
              return self._assert_field_value(args["response"], args["json_path"], args["expected"])
          if tool == "assert_no_errors":
              return self._assert_no_errors(args["response"])
          raise ValueError(f"Unknown tool: {tool}")
      # ... helper methods follow
  ```
- [ ] **5.2.2** Define `BundledProvider` abstract base in `packages/mcp/src/suitest_mcp/bundled/base.py` if not already present from M1c. Provides `name`, `kind`, `tools`, `health()`, `invoke(tool, args)`, and default `tools_list()` implementation that returns `self.tools`.

### 5.3 Registration

- [ ] **5.3.1** In `packages/mcp/src/suitest_mcp/registry.py`, register `GraphQlProvider` in the bundled list. Update default routing table to map `BE_GRAPHQL → graphql-mcp` (already present in routing.py from M1c, just verify).
- [ ] **5.3.2** On startup, the workspace bootstrap helper (M1a `seed_bundled_mcp_providers`) auto-inserts a `mcp_providers` row for each new bundled provider. Verify the helper iterates all bundled providers; if it only knows 3 from M1c, extend it to discover via `registry.list_bundled()`.

### 5.4 Tests

- [ ] **5.4.1** Fixture: `testcontainers` running `graphql-faker` Docker image (`apisguru/graphql-faker:latest`) or a minimal stub server (FastAPI + strawberry-graphql) under `packages/mcp/tests/fixtures/graphql_server.py`.
- [ ] **5.4.2** Pytest `packages/mcp/tests/test_bundled_graphql.py`:
  - `test_introspect_returns_schema` — invoke `introspect` → response has `__schema` key.
  - `test_query_happy_path` — invoke `query` with simple `{ hello }` → response has `data.hello`.
  - `test_query_with_variables` — parameterized query → variables substituted, expected result.
  - `test_mutation_writes` — invoke `mutation` adding a user → assert response data.
  - `test_assert_field_value_pass` — pass-through assertion with `json_path="$.data.hello"`.
  - `test_assert_field_value_fail` — expected mismatch → result.ok=False, error_message set.
  - `test_assert_no_errors_when_present_fails` — response has `errors` field → result.ok=False.
  - `test_health_returns_true_when_up` — running container → health=True.
  - `test_health_returns_false_when_down` — point at nonexistent URL → health=False.
- [ ] **5.4.3** Run tests. Green.
- [ ] **5.4.4** Commit: `feat(mcp): bundled graphql-mcp provider (Closes #M2-10)`.

---

## Task 6: Bundled MCP — mongo-mcp

In-process MCP using `motor`.

### 6.1 Dependencies

- [ ] **6.1.1** Add to `packages/mcp/pyproject.toml`:
  - `motor >= 3.4.0`

### 6.2 Provider module

- [ ] **6.2.1** Create `packages/mcp/src/suitest_mcp/bundled/mongo.py`:
  - `class MongoProvider(BundledProvider)`:
    - `name = "mongo-mcp"`; `kind = "mongo"`.
    - Tools (each with strict JSON schema):
      - `find(collection, filter, projection?, limit?, sort?)` → list of docs.
      - `find_one(collection, filter, projection?)` → single doc or null.
      - `insert(collection, doc)` → `{inserted_id}`.
      - `insert_many(collection, docs)` → `{inserted_ids}`.
      - `update(collection, filter, update, upsert?)` → `{matched, modified}`.
      - `delete(collection, filter, many?)` → `{deleted_count}`.
      - `assert_doc_exists(collection, filter)` → ok if ≥1 match else fail.
      - `assert_count(collection, filter, expected)` → ok if count==expected else fail.
      - `aggregate(collection, pipeline)` → list of result docs.
    - `__init__` reads `config["connection_uri"]`, decrypts secrets.
    - `async def _client(self) -> AsyncIOMotorClient` — lazy, pooled (Motor uses pymongo connection pool internally).
    - `async def health(self) -> bool` — issue `ping` admin command.

### 6.3 Tests

- [ ] **6.3.1** Use `testcontainers.mongodb.MongoDbContainer`.
- [ ] **6.3.2** Pytest `packages/mcp/tests/test_bundled_mongo.py`:
  - `test_insert_then_find_one` — insert a doc → find_one with matching filter → returns doc.
  - `test_insert_many` — insert 5 docs → find with empty filter → 5 results.
  - `test_update_one` — insert → update with `{$set: {field: "new"}}` → find → assert updated.
  - `test_delete_one` — insert → delete by filter → find → empty.
  - `test_assert_doc_exists_pass` — insert → assert_doc_exists → ok.
  - `test_assert_doc_exists_fail` — no docs → assert_doc_exists → ok=False.
  - `test_assert_count_pass` — insert 3 → assert_count expected=3 → ok.
  - `test_assert_count_fail` — insert 3 → assert_count expected=5 → ok=False.
  - `test_aggregate_pipeline` — `[{$match: {...}}, {$group: {...}}]` → returns aggregated.
  - `test_health_returns_true_when_up`, `test_health_returns_false_when_down`.
- [ ] **6.3.3** Run tests. Green.
- [ ] **6.3.4** Commit: `feat(mcp): bundled mongo-mcp provider (Closes #M2-10)`.

---

## Task 7: Bundled MCP — mysql-mcp

In-process MCP using `aiomysql`.

### 7.1 Dependencies

- [ ] **7.1.1** Add to `packages/mcp/pyproject.toml`:
  - `aiomysql >= 0.2.0`

### 7.2 Provider module

- [ ] **7.2.1** Create `packages/mcp/src/suitest_mcp/bundled/mysql.py`:
  - `class MySqlProvider(BundledProvider)`:
    - `name = "mysql-mcp"`; `kind = "mysql"`.
    - Tools:
      - `query(sql, params?)` — read-only SELECT (enforced by `_is_select_only(sql)` guard; reject SQL containing DML/DDL keywords case-insensitive). Returns `{rows: [...], rowcount: int}`.
      - `exec(sql, params?)` — DML (INSERT/UPDATE/DELETE) — explicitly allowed.
      - `assert_row_exists(table, where_clause, params?)` — `SELECT 1 FROM table WHERE ... LIMIT 1`.
      - `assert_row_count(table, where_clause, params?, expected)` — `SELECT COUNT(*) ...`.
      - `insert(table, values: dict)` — INSERT INTO ... VALUES.
      - `delete(table, where_clause, params?)` — DELETE FROM ... WHERE.
    - `__init__` reads `config["connection_uri"]` of form `mysql://user:pass@host:port/db`.
    - Connection pool via `aiomysql.create_pool` lazily.
    - `async def health(self) -> bool` — `SELECT 1`.

### 7.3 Tests

- [ ] **7.3.1** Use `testcontainers.mysql.MySqlContainer(image="mysql:8")`.
- [ ] **7.3.2** Pytest `packages/mcp/tests/test_bundled_mysql.py`:
  - Bootstrap test schema via direct connection: create table `users(id INT PK AUTO_INCREMENT, name VARCHAR(50), email VARCHAR(100))`.
  - `test_insert_then_query` — insert one → query → 1 row.
  - `test_query_rejects_dml` — `query` with `INSERT INTO ...` → result.ok=False with error_code=`MYSQL_DML_FORBIDDEN`.
  - `test_exec_allows_dml` — same statement via `exec` → ok.
  - `test_assert_row_exists_pass` — insert → assert with matching where → ok.
  - `test_assert_row_exists_fail` — no row → ok=False.
  - `test_assert_row_count` — insert 3 → assert_row_count expected=3 → ok.
  - `test_parameter_binding_prevents_injection` — pass user input via params, not string concat → assert binding behaves correctly.
  - `test_delete_returns_count` — insert 2 → delete with where → assert deleted_count=2.
  - `test_health_returns_true_when_up`, `test_health_returns_false_when_down`.
- [ ] **7.3.3** Run tests. Green.
- [ ] **7.3.4** Commit: `feat(mcp): bundled mysql-mcp provider (Closes #M2-10)`.

---

## Task 8: Bundled MCP — kubernetes-mcp

Subprocess-style provider via `kubernetes_asyncio` (in-process Python; despite the spec listing it as subprocess wrapper, the Python async client is in-process and lighter than spawning kubectl). The "subprocess" naming refers to its kind of operation, not the implementation transport.

### 8.1 Dependencies

- [ ] **8.1.1** Add to `packages/mcp/pyproject.toml`:
  - `kubernetes_asyncio >= 30.0.0`

### 8.2 Provider module

- [ ] **8.2.1** Create `packages/mcp/src/suitest_mcp/bundled/kubernetes.py`:
  - `class KubernetesProvider(BundledProvider)`:
    - `name = "kubernetes-mcp"`; `kind = "kubernetes"`.
    - `__init__(self, config: dict)`:
      - `kubeconfig_path = config.get("kubeconfig_path")` (defaults to `~/.kube/config`).
      - `context = config.get("context")`.
      - `in_cluster = config.get("in_cluster", False)`.
    - `async def _load_config()`:
      - If `in_cluster`: `kubernetes_asyncio.config.load_incluster_config()`.
      - Else: `await kubernetes_asyncio.config.load_kube_config(config_file=kubeconfig_path, context=context)`.
    - Tools:
      - `get(api_version, kind, namespace, name)` → fetch single resource.
      - `list(api_version, kind, namespace?, label_selector?)` → list resources.
      - `assert_replicas_ready(namespace, deployment, expected_min)` → assert `status.readyReplicas >= expected_min`.
      - `assert_pod_status(namespace, pod_name, expected_phase)` → assert `status.phase == expected_phase`.
      - `exec_pod(namespace, pod, container?, command: list[str], stdin?, timeout_seconds?)` → returns stdout/stderr.
      - `port_forward(namespace, pod, local_port, remote_port, duration_seconds?)` → returns local_port (held alive for duration via background task).
      - `apply(manifest_yaml_or_json)` → server-side apply via `kubernetes_asyncio.utils.create_from_yaml`. Validate it's a known kind first.
      - `delete(api_version, kind, namespace, name)`.
    - `async def health(self) -> bool` — `CoreV1Api.get_api_resources()` → ok if status<500.

### 8.3 Tests

- [ ] **8.3.1** Use `testcontainers.k3s.K3SContainer` (k3s in container; simpler than kind). Fixture `k3s_container` exposes kubeconfig via `container.config_yaml`.
- [ ] **8.3.2** Pytest `packages/mcp/tests/test_bundled_kubernetes.py`:
  - `test_list_default_namespace_pods` — list pods in `kube-system` → ≥1.
  - `test_get_default_service` — get `Service kubernetes` in `default` namespace → ok.
  - `test_apply_then_get_deployment` — apply a 1-replica nginx deployment manifest → wait for ready (up to 60s) → get → readyReplicas==1.
  - `test_assert_replicas_ready_pass` — after apply → assertion ok.
  - `test_assert_replicas_ready_fail` — expected_min=5 → ok=False.
  - `test_assert_pod_status_running` — wait for pod → assertion ok with phase=`Running`.
  - `test_exec_pod_returns_stdout` — exec `echo hello` inside the nginx pod → stdout contains "hello".
  - `test_delete_deployment` — apply → delete → list → not present.
  - `test_health_returns_true`, `test_health_returns_false_when_kubeconfig_invalid`.
- [ ] **8.3.3** If `k3s` testcontainer is too heavy for CI, alternate fixture using `mock_kubernetes_api` (FastAPI app emulating the small subset of API endpoints exercised). Document in test docstring which mode is active (default real; CI flag `SUITEST_K8S_MOCK=1` uses mock).
- [ ] **8.3.4** Run tests. Green.
- [ ] **8.3.5** Commit: `feat(mcp): bundled kubernetes-mcp provider (Closes #M2-10)`.

---

## Task 9: Bundled MCP — grpc-mcp

Subprocess wrapper over stdio (grpcio doesn't ship with native Python in-process server reflection client utility in a way that integrates with our pool; we use stdio for symmetry with other process-isolated MCPs).

### 9.1 Dependencies

- [ ] **9.1.1** Add to `packages/mcp/pyproject.toml`:
  - `grpcio >= 1.62.0`
  - `grpcio-tools >= 1.62.0`
  - `grpcio-reflection >= 1.62.0`

### 9.2 Provider module

- [ ] **9.2.1** Create `packages/mcp/src/suitest_mcp/bundled/grpc.py`:
  - `class GrpcProvider(BundledProvider)`:
    - `name = "grpc-mcp"`; `kind = "grpc"`; `transport = "in_process"` (Python `grpc.aio` client is in-process).
    - `__init__(self, config: dict)`:
      - `target = config["target"]` (e.g. `localhost:50051`).
      - `tls = config.get("tls", False)`.
      - `proto_dirs: list[str] = config.get("proto_dirs", [])`.
      - `metadata: dict = config.get("metadata", {})`.
    - Tools:
      - `reflect()` → use `grpc.reflection.v1alpha` to list services + methods.
      - `invoke(service, method, request: dict, timeout_seconds?: float, stream?: bool)` → if `stream=False` (default), unary invoke; for streaming, collect first N messages (capped).
      - `assert_status(response, expected_code)` — gRPC status code comparison.
      - `assert_field(response, field_path, expected)` — JSON-path-style on the response dict.
      - `stream(service, method, request: dict, max_messages?: int)` — read server-streaming response, collect up to `max_messages`.
    - Reflection uses dynamic message construction via `grpc_reflection` + `google.protobuf.descriptor_pool`. If `proto_dirs` provided, also load static `.proto` files via `grpc_tools.protoc`.
    - `async def health(self) -> bool` — `reflect()` returns ≥1 service → ok.

### 9.3 Tests

- [ ] **9.3.1** Fixture: testcontainer running `grpc/grpc-server-reflection-test` or a custom grpc-faker. Alternative: bundle a tiny test server `packages/mcp/tests/fixtures/grpc_server.py` exposing 1 service `EchoService.Echo(EchoRequest{msg}) -> EchoResponse{msg}`. Launch in fixture via `asyncio.create_subprocess_exec`.
- [ ] **9.3.2** Pytest `packages/mcp/tests/test_bundled_grpc.py`:
  - `test_reflect_lists_echo_service` — invoke `reflect` → response includes `EchoService`.
  - `test_invoke_echo_unary` — invoke `EchoService.Echo` with `{"msg": "hello"}` → response.msg == "hello".
  - `test_invoke_with_metadata` — pass metadata; server echoes back.
  - `test_invoke_unknown_method` — invoke nonexistent method → ok=False, error_code maps to UNIMPLEMENTED.
  - `test_assert_status_pass` — response with status OK, expected OK → ok.
  - `test_assert_field_pass` — assert `response.msg == "hello"` → ok.
  - `test_stream_collects_messages` — invoke server-streaming `EchoService.StreamEcho` (provided in fixture) → collect 3 messages → list length=3.
  - `test_health_returns_true`, `test_health_returns_false_when_target_unreachable`.
- [ ] **9.3.3** Run tests. Green.
- [ ] **9.3.4** Commit: `feat(mcp): bundled grpc-mcp provider (Closes #M2-10)`.

---

## Task 10: Custom MCP registration end-to-end

Complete CRUD that M1a scaffolded as read-only. Add POST/PATCH/DELETE plus `/health`, `/test`, `/invoke`, `/tools`. Tool discovery cached on registration.

### 10.1 Pydantic schemas

- [ ] **10.1.1** Append/extend `packages/shared/suitest_shared/schemas/mcp.py`:
  ```python
  class McpProviderCreateRequest(BaseModel):
      name: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")]
      kind: str
      endpoint: str
      transport: Literal["stdio", "sse", "ws", "in_process"]
      config: dict[str, object] = Field(default_factory=dict)
      secrets: dict[str, str] = Field(default_factory=dict, repr=False)
      is_default_for_targets: list[str] = Field(default_factory=list)

  class McpProviderUpdateRequest(BaseModel):
      endpoint: str | None = None
      config: dict[str, object] | None = None
      secrets: dict[str, str] | None = Field(default=None, repr=False)
      is_default_for_targets: list[str] | None = None

  class McpProviderTestResponse(BaseModel):
      ok: bool
      latency_ms: int
      tools_discovered: int
      version: str | None = None
      error: str | None = None

  class McpToolInvokeRequest(BaseModel):
      tool: str
      input: dict[str, object] = Field(default_factory=dict)

  class McpToolInvokeResponse(BaseModel):
      ok: bool
      output: dict[str, object]
      stdout: str = ""
      stderr: str = ""
      duration_ms: int
      error_code: str | None = None
      error_message: str | None = None

  class McpProviderToolsResponse(BaseModel):
      provider_id: str
      tools: list[McpToolSchema]
      discovered_at: datetime
  ```

### 10.2 Service + repository

- [ ] **10.2.1** Extend `apps/api/src/suitest_api/services/mcp_provider_service.py`:
  - `async def register(self, workspace_id, user_id, request) -> McpProviderPublic`:
    - Validate uniqueness of `name` within workspace.
    - Encrypt `secrets` via `packages/core/crypto.py` AES-GCM helper.
    - Insert row with `health_status="unknown"`.
    - Immediately probe: spawn/connect transport, MCP `initialize` handshake, `tools/list`.
    - Persist discovered tools in `config_json.tools` (list of `{name, description, input_schema}`).
    - Mark `health_status="ok"` + `last_health_at=now`.
    - If probe fails, rollback (delete row) + raise `McpRegistrationFailed(message=...)` → 422.
    - Audit `mcp_provider.registered`.
  - `async def update(self, provider_id, workspace_id, user_id, request) -> McpProviderPublic`:
    - Load row; assert workspace match (else 404).
    - Reject if `name` is a bundled provider name (bundled is immutable). Use `registry.is_bundled(name)` check.
    - Apply patch; if `endpoint` or `secrets` changed → re-probe.
    - Audit `mcp_provider.updated`.
  - `async def delete(self, provider_id, workspace_id, user_id) -> None`:
    - Reject if bundled.
    - Reject if referenced by `test_steps.mcp_provider` (count > 0) — return 409 with details. (Bypass via `?force=true` only by ADMIN/OWNER → set step.mcp_provider to default for target_kind.)
    - Soft delete by setting `deleted_at` (add column if not present in migration 0.2) OR hard delete (simpler for v1.0; choose hard delete and document).
    - Audit.
  - `async def health(self, provider_id, workspace_id) -> McpHealthStatus`:
    - Load row; spawn transient session; invoke `tools/list`; measure latency.
    - Update row `health_status` + `last_health_at`.
    - Return status.
  - `async def discover(self, provider_id, workspace_id) -> McpProviderToolsResponse`:
    - Same as health, but persist tools list + return.
  - `async def invoke(self, provider_id, workspace_id, user_id, request) -> McpToolInvokeResponse`:
    - Role gate (caller must be `ADMIN` or `OWNER`).
    - Rate limit 10/min per user (Redis token bucket).
    - Invoke via `mcp_invoker.invoke(provider_name, tool, args)`.
    - Audit `mcp_provider.invoked` with `invocation_source="tool_browser"`.

### 10.3 Endpoints

- [ ] **10.3.1** Update `apps/api/src/suitest_api/routers/mcp.py` to include:
  ```python
  @router.post("/providers", response_model=McpProviderPublic, status_code=201)
  @router.patch("/providers/{provider_id}", response_model=McpProviderPublic)
  @router.delete("/providers/{provider_id}", status_code=204)
  @router.post("/providers/{provider_id}/health", response_model=McpHealthStatus)
  @router.post("/providers/{provider_id}/test", response_model=McpProviderTestResponse)
  @router.post("/providers/{provider_id}/invoke", response_model=McpToolInvokeResponse)
  @router.get("/providers/{provider_id}/tools", response_model=McpProviderToolsResponse)
  ```
- [ ] **10.3.2** Background task `mcp_discovery_refresh` registered with ARQ cron (`*/24 hours`):
  - For each provider where `last_health_at < now - 24h`: re-run discovery, update `config_json.tools`.

### 10.4 Tests

- [ ] **10.4.1** Pytest `apps/api/tests/test_mcp_provider_crud.py`:
  - `test_register_custom_filesystem_mcp` — register `@modelcontextprotocol/server-filesystem` via npx:
    - body: `{"name": "fs-mcp", "kind": "filesystem", "endpoint": "npx -y @modelcontextprotocol/server-filesystem /tmp", "transport": "stdio", ...}`
    - assert 201, response.tools includes `read_file`, `write_file`, `list_directory`.
  - `test_register_invalid_endpoint_returns_422` — bogus stdio command → handshake fails → 422 `MCP_REGISTRATION_FAILED`.
  - `test_register_duplicate_name_409` — register same name twice → second 409.
  - `test_register_reserved_bundled_name_409` — try to register `name="playwright-mcp"` → 409.
  - `test_register_name_invalid_pattern_422` — `name="Has Spaces"` → 422 pattern violation.
  - `test_update_endpoint_reprobe` — register → update endpoint → tools re-discovered.
  - `test_update_bundled_returns_409` — patch `playwright-mcp` → 409.
  - `test_delete_with_steps_referencing_409` — create case with step using custom mcp → delete provider → 409 unless `force=true`.
  - `test_delete_force_reassigns_step_mcp_to_default` — delete with `?force=true` → step.mcp_provider reset to routing default for its target_kind.
  - `test_health_endpoint_updates_status` — POST `/health` → status changes if probe fails.
  - `test_invoke_admin_only` — viewer role calls `/invoke` → 403.
  - `test_invoke_rate_limited` — 11 calls in 1 min → 11th returns 429 with `Retry-After`.
  - `test_invoke_audit_logged` — invoke → audit row created with `invocation_source="tool_browser"`.
  - `test_tools_endpoint_returns_cached_catalog` — GET `/tools` → returns persisted `config_json.tools`.
  - `test_discovery_refresh_background_task` — manually set `last_health_at` to 25h ago, run task → tools re-discovered.
- [ ] **10.4.2** Integration test `apps/api/tests/integration/test_filesystem_mcp_e2e.py`:
  - Spin up Docker container with `node:20`, mount `/tmp` volume.
  - Register `npx -y @modelcontextprotocol/server-filesystem /tmp` as custom MCP.
  - `POST /providers/{id}/invoke` with `tool="write_file"`, args=`{"path": "/tmp/test.txt", "content": "hello"}` → ok.
  - Then invoke `tool="read_file"`, args=`{"path": "/tmp/test.txt"}` → result.output.content=="hello".
  - Verify result, audit trail, no leaked secrets.
- [ ] **10.4.3** Run tests. Green.
- [ ] **10.4.4** Commit: `feat(mcp): custom MCP registration CRUD + discovery (Closes #M2-6 #M2-7)`.

---

## Task 11: MCP tool browser UI

UI under Settings → Integrations → MCP Servers → Tools tab.

### 11.1 Frontend route + components

- [ ] **11.1.1** Update `apps/web/src/routes/(app)/integrations/mcp/$providerId.tsx`:
  - Sub-tabs: Tools · History · Config (read existing M1b scaffold; ensure tab strip present).
  - Tools sub-tab content:
    - Fetch `GET /mcp/providers/:id/tools` via TanStack Query.
    - Render list of tools. Each row: name (mono), description, expand caret.
    - Expand → show JSON schema in pretty-print (use `react-json-tree` or shadcn-styled custom renderer).
    - "Try it" button → opens drawer with auto-generated form.
- [ ] **11.1.2** Create `apps/web/src/components/integrations/ToolTryItForm.tsx`:
  - Props: `providerId: string`, `tool: McpToolSchema`, `onClose: () => void`.
  - Renders form fields from `tool.inputSchema`:
    - `type: string` → `<Input>` (use `format: date-time` → `<DatePicker>`, `format: email` → `<Input type="email">`).
    - `type: integer/number` → `<Input type="number">`.
    - `type: boolean` → `<Switch>`.
    - `type: object` → nested form (recurse 1 level; deeper → Monaco JSON editor fallback).
    - `type: array` → repeating row UI with add/remove buttons.
    - `enum` → `<Select>`.
  - On submit → `POST /mcp/providers/:id/invoke` body `{tool: tool.name, input: form_values}`.
  - Result panel below form: stdout (mono), stderr (mono, red border if non-empty), output JSON (mono pretty-print), latency badge.
  - Loading state during invoke; error states.
- [ ] **11.1.3** Role gate: hide entire Tools sub-tab unless `user.role in ['ADMIN', 'OWNER']` (read from `/auth/me` Zustand store).
- [ ] **11.1.4** Add `<DisabledTooltip reason="Requires ADMIN role">` on the Try-it button for non-admins (visible but disabled — helpful onboarding hint).

### 11.2 Schema-to-form helper

- [ ] **11.2.1** Create `apps/web/src/lib/schema-form.ts`:
  - `function fieldsFromSchema(schema: JsonSchema): FormField[]` — flatten schema into field list with metadata: `{name, type, required, defaultValue, enum?, format?, minimum?, maximum?, nested?}`.
  - Pure function; unit test it heavily.

### 11.3 Tests

- [ ] **11.3.1** Vitest `apps/web/src/lib/schema-form.test.ts`:
  - `flat_string_field` — `{type: object, properties: {name: {type: string}}, required: [name]}` → 1 field.
  - `enum_field` — `{type: string, enum: ["a","b"]}` → field has enum.
  - `nested_object_one_level` → flattened with `parent.child` name.
  - `array_field` → array marker.
  - `boundaries` — minimum/maximum carried.
- [ ] **11.3.2** Vitest `apps/web/src/components/integrations/ToolTryItForm.test.tsx`:
  - Render form for filesystem-mcp `read_file` tool schema → input has `path` field.
  - Submit form → mocked fetch called with `{tool: "read_file", input: {path: "/tmp/x"}}`.
  - Result panel renders mocked output.
  - Loading state when invoke pending.
  - Error state on rejection.
- [ ] **11.3.3** Playwright E2E `apps/web/e2e/mcp-tool-browser.spec.ts`:
  - Login as ADMIN → navigate to MCP tab → click provider → switch to Tools → expand tool → fill form → invoke → assert result panel shown.
- [ ] **11.3.4** Run tests. Green.
- [ ] **11.3.5** Commit: `feat(web): MCP tool browser + try-it form (Closes #M2-8)`.

---

## Task 12: Routing override per workspace

UI drag-drop + API PUT `/mcp/routing`. Persists in `WorkspaceCapability.routing_overrides_json` (column added in this task if not present from M1a).

### 12.1 DB column

- [ ] **12.1.1** Check if `workspace_capabilities.routing_overrides_json` already exists. If not, add migration `2026_05_26_m2_routing_overrides.py`:
  - `op.add_column("workspace_capabilities", sa.Column("routing_overrides_json", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))`.
  - Downgrade drops column.

### 12.2 Pydantic + Service + Endpoint

- [ ] **12.2.1** Append to `packages/shared/suitest_shared/schemas/mcp.py`:
  ```python
  class RoutingOverridesRequest(BaseModel):
      routing_overrides: dict[str, str] = Field(default_factory=dict)
      # keys: TargetKind enum values; values: provider_id

  class RoutingOverridesResponse(BaseModel):
      routing_overrides: dict[str, str]
      effective_routing: dict[str, str]  # merged: defaults + overrides
      updated_at: datetime
  ```
- [ ] **12.2.2** Extend `apps/api/src/suitest_api/services/mcp_routing_service.py`:
  - `async def get(self, workspace_id) -> RoutingOverridesResponse`:
    - Load `workspace_capabilities.routing_overrides_json`.
    - Compute effective by merging global default (from `packages/mcp/routing.py`) + per-workspace overrides.
  - `async def update(self, workspace_id, user_id, request) -> RoutingOverridesResponse`:
    - Validate each `provider_id` exists in workspace.
    - Validate keys are valid `TargetKind` values.
    - Persist; audit `mcp_routing.updated`; emit WS `mcp.routing.changed`.
- [ ] **12.2.3** Endpoints in `apps/api/src/suitest_api/routers/mcp.py`:
  ```python
  @router.get("/routing", response_model=RoutingOverridesResponse)
  @router.put("/routing", response_model=RoutingOverridesResponse)
  ```
  Both require role `ADMIN` or `OWNER`.

### 12.3 Runner integration

- [ ] **12.3.1** Update `packages/mcp/src/suitest_mcp/routing.py` resolution function:
  - Existing M1c `resolve(workspace_id, target_kind, explicit_step_mcp)`. Extend to consult `routing_overrides_json` after explicit step setting but before global defaults:
    1. If `step.mcp_provider` set → use it.
    2. Else if `workspace.routing_overrides_json[target_kind]` set → use that provider id.
    3. Else use global default table.

### 12.4 Frontend

- [ ] **12.4.1** Update `apps/web/src/components/integrations/McpServersTab.tsx`:
  - Below the provider list, add "Routing config" section.
  - For each `target_kind` (BE_REST, BE_GRAPHQL, BE_GRPC, FE_WEB, FE_MOBILE, DATA, INFRA, CUSTOM):
    - Show ordered list of providers (compatible by kind heuristic).
    - First item = current routing for this target_kind (default or override).
    - Drag-drop reorder via `@dnd-kit/sortable` (already installed M1d).
    - Save reorder → PUT `/mcp/routing` body `{routing_overrides: {target_kind: first_provider_id}}`.
  - Optimistic update; toast on success; rollback on error.

### 12.5 Tests

- [ ] **12.5.1** Pytest `apps/api/tests/test_mcp_routing.py`:
  - `test_get_routing_returns_defaults_when_no_overrides`.
  - `test_put_routing_persists_override`.
  - `test_put_routing_invalid_target_kind_422`.
  - `test_put_routing_unknown_provider_id_404`.
  - `test_put_routing_cross_workspace_provider_404`.
  - `test_put_routing_emits_ws_event` — capture WS broadcast.
  - `test_routing_affects_run_execution` — set override `FE_WEB → custom-playwright-mcp-id` → enqueue run with FE_WEB step missing `step.mcp_provider` → executor uses overridden provider (verify via mocked invoker).
- [ ] **12.5.2** Vitest `apps/web/src/components/integrations/McpRoutingConfig.test.tsx`:
  - Drag provider to top → fetch called with PUT body.
  - Rollback on rejection.
- [ ] **12.5.3** Run tests. Green.
- [ ] **12.5.4** Commit: `feat(mcp): per-workspace routing override (Closes #M2-9)`.

---

## Task 13: Mixed-MCP test case execution proven E2E

Author the canonical "Checkout E2E" case from GENERATORS.md §9. Wire into M1a seed. E2E test proves runner switches MCP per step. Document in `examples/`.

### 13.1 Seed extension

- [ ] **13.1.1** Extend `packages/db/suitest_db/seed.py` (the M1a-9 seed module):
  - Add a 19th test case to suite "Checkout" in project "Nusantara Retail":
    - id: deterministic from slug e.g. `tc_seed_checkout_mixed_mcp`.
    - public_id: `TC-1900` (avoid collision with M1a public_id sequence by using fixed reserved range).
    - name: "Checkout: signed-in user pays for cart with valid card".
    - target_kind: `MIXED`.
    - source: `MCP` (rationale: mixed-MCP demos use MCP source enum).
    - generated_from: `{"source": "PRD", "example": "mixed_mcp_checkout"}`.
    - priority: P0.
    - tags: `["checkout", "e2e", "critical-path", "mixed-mcp"]`.
    - status: ACTIVE.
    - steps: 5 steps verbatim from GENERATORS.md §9 (postgres-mcp seed, api-http-mcp login, playwright-mcp checkout, api-http-mcp verify order, postgres-mcp verify DB).
- [ ] **13.1.2** Seed is idempotent (ON CONFLICT DO NOTHING).

### 13.2 E2E run test

- [ ] **13.2.1** Add integration test `apps/runner/tests/integration/test_mixed_mcp_run.py`:
  - Bring up dependencies: postgres, redis, minio, playwright browser (via existing M1c testcontainers harness).
  - Bootstrap test fixtures:
    - Seed an `orders` API stub (FastAPI app launched in subprocess on port 8081) that:
      - `POST /auth/login` → returns `{"token": "test-token"}`.
      - `GET /orders/:id` → returns `{"id": ..., "status": "PAID", "total_cents": 1999}`.
    - Seed a static frontend page (testcontainer nginx serving 3 pages: `/login`, `/checkout`, `/order/confirmation/:id`) with simulated checkout form. Simulated JS injects element with `data-test="order-id"` containing a stable id after "pay".
    - Apply the postgres schema (users, carts, cart_items, orders, payments tables) via SQL fixture.
  - Resolve seed variables in step.code via runtime context: `{{base_url}}=http://localhost:8081`, `{{app_url}}=http://localhost:9090`, `{{user_id}}=user-deadbeef`, etc.
  - Trigger run via `POST /api/v1/test-cases/TC-1900/run` (using API client fixture).
  - Watch run via WS subscription on `run:{runId}` events.
  - Assertions:
    - All 5 steps PASS.
    - Each step's `mcp_provider` matches expected: postgres-mcp, api-http-mcp, playwright-mcp, api-http-mcp, postgres-mcp.
    - Runner switches MCP session between steps without restarting the run.
    - Each step's `RunStep.duration_ms > 0` and `outcome = PASS`.
    - DB state at end matches assertions in step 5 (verified by separate direct query in test).
    - At least 1 screenshot artifact uploaded for the playwright step (kind=`SCREENSHOT`).

### 13.3 Example documentation

- [ ] **13.3.1** Create `examples/mixed-mcp-checkout/README.md`:
  - Walkthrough: what the case demonstrates, how to run locally (`docker compose up`, `make seed`, `make run-case TC-1900`).
  - Explains step-by-step what each MCP does.
  - Architecture diagram (ASCII or PlantUML rendered) showing data flow: API ↔ Suitest runner ↔ {postgres-mcp, api-http-mcp, playwright-mcp}.
  - Notes the connection pooling behavior (each provider pool reused across the 5 steps).
- [ ] **13.3.2** Add `examples/mixed-mcp-checkout/fixtures/` with:
  - `schema.sql` (DDL for the demo orders DB).
  - `stub-server.py` (FastAPI orders API stub).
  - `frontend/` static HTML.
  - `docker-compose.example.yml` defining the entire mini-stack.

### 13.4 Commits

- [ ] **13.4.1** Run tests. Green.
- [ ] **13.4.2** Commit: `feat(seed): mixed-MCP checkout demo case + E2E proof (Closes #M2-11)`.

---

## Task 14: Generation modal UI — 3 deterministic strategies

UI_SPEC § 3.2.1.5 wizard. 5 steps. Wires each deterministic strategy to backend SSE.

### 14.1 Modal component

- [ ] **14.1.1** Create `apps/web/src/components/cases/GenerateModal.tsx`:
  - shadcn Dialog, `max-w-[920px]`, `max-h-[90vh]`.
  - State: `step: 1..5`, `targetKind`, `source`, `mcpProviderId`, `strategy`, `streamingCases: TestCaseDraft[]`, `selectedIds: Set<string>`.
  - Stepper header with 5 dots, active highlighted.
- [ ] **14.1.2** Step 1: `apps/web/src/components/cases/generate/StepTargetPicker.tsx`:
  - 6 cards grid (3×2) per UI_SPEC table.
  - ZERO disables "Mixed PRD-driven" with `<DisabledTooltip>`.
  - Click → set `targetKind` + auto-set default `mcpProviderId` from `/capabilities.mcpProviders` filtered by kind compatibility.
- [ ] **14.1.3** Step 2: `apps/web/src/components/cases/generate/StepSource.tsx`:
  - Render input based on `targetKind`:
    - `BE_REST` → tabs: OpenAPI URL / paste spec / upload spec file.
    - `FE_WEB` → tabs: Crawl URL / Record session. URL input + max depth slider + auth picker for crawl; "Start recording" button for record.
    - `DATA` → connection URL field (read-only role hint).
    - others → free text or upload.
  - On change → invoke `POST /generators/classify` with the input → display classification result inline ("We think this is a `BE_REST` target — proceed?"). User can confirm or override.
- [ ] **14.1.4** Step 3: `apps/web/src/components/cases/generate/StepMcpProvider.tsx`:
  - Show `<McpProviderPill>` of auto-selected.
  - "Change" link → opens dropdown of providers compatible with target_kind, sorted by health then recency.
  - "Manage MCP servers" link → opens `/integrations?tab=mcp` in new tab.
- [ ] **14.1.5** Step 4: `apps/web/src/components/cases/generate/StepStrategy.tsx`:
  - Radio: Deterministic / AI-enrich / AI-only.
  - AI options disabled in ZERO with tooltip.
  - For Deterministic + `BE_REST`/OpenAPI → automatically maps to OpenAPI generator.
  - For Deterministic + `FE_WEB` → recorder OR crawler (sub-selector based on Step 2 input).
- [ ] **14.1.6** Step 5: `apps/web/src/components/cases/generate/StepReview.tsx`:
  - On entering this step: open SSE connection via `EventSource(`/api/v1/generators/${endpoint}`, ...) where `endpoint` = `openapi` / `crawler` / `recorder/sessions/{id}/finalize` depending on strategy. Post body via a separate fetch first since EventSource is GET-only; switch to `fetchEventSource` from `@microsoft/fetch-event-source` (already a small dep) to support POST + SSE.
  - For each `event: case`: prepend the case to `streamingCases`, animate slide-in (Tailwind `animate-in slide-in-from-top-4 fade-in duration-300`).
  - For each `event: progress`: update progress message in header ("Reading spec…", "Generating contract tests…").
  - On `event: complete`: replace Generate button with "Add N to suite".
  - On `event: error`: show inline error banner with message + retry button.
  - Per-case checkbox (default checked); inline-edit case name; "Expand" → side drawer showing all steps.
  - Bulk action footer: "Add {selected count} to suite" → POST `/test-cases` batch (one call per case for v1.0; future: POST `/test-cases/batch`).

### 14.2 SSE client helper

- [ ] **14.2.1** Add `apps/web/src/lib/sse-post.ts`:
  - `async function ssePost<TEvent>(url: string, body: unknown, opts: {onEvent: (ev: TEvent) => void, onError?: (e: Error) => void, signal?: AbortSignal})`.
  - Implemented via `fetch` with `Accept: text/event-stream` + streaming body parser (split on `\n\n`, parse `event:` and `data:` lines).
- [ ] **14.2.2** Vitest unit tests for parser.

### 14.3 Tests

- [ ] **14.3.1** Vitest `apps/web/src/components/cases/GenerateModal.test.tsx`:
  - Render modal in ZERO tier → step 1 shows AI-driven cards disabled.
  - Click "Backend API" → step 2 input visible.
  - Type OpenAPI URL → classifier hint appears.
  - Navigate to step 3 → MCP provider auto-selected with health pill.
  - Step 4 → deterministic radio pre-selected, AI radios disabled with tooltip.
  - Step 5 → mock SSE stream emitting 3 cases → all 3 appear in list with slide-in classes.
  - Bulk save → mocked POST `/test-cases` called 3 times (or once if batch endpoint exists).
- [ ] **14.3.2** Playwright E2E `apps/web/e2e/generate-modal-deterministic.spec.ts`:
  - ZERO workspace → open modal → Backend API → paste OpenAPI URL (httpbin local fixture) → generate → ≥10 cases stream in → uncheck 2 → save → assert suite has N-2 new cases visible.
- [ ] **14.3.3** Run tests. Green.
- [ ] **14.3.4** Commit: `feat(web): generation modal with 3 deterministic strategies (Closes #M2-5)`.

---

## Task 15: Test code export — Playwright target

Jinja2 templates emit runnable Playwright TS. Per-MCP step translation.

### 15.1 Dependencies

- [ ] **15.1.1** Add to `packages/agent/pyproject.toml`:
  - `jinja2 >= 3.1.3`

### 15.2 Exporter module

- [ ] **15.2.1** Create `packages/agent/src/suitest_agent/exporters/__init__.py` (empty docstring).
- [ ] **15.2.2** Create `packages/agent/src/suitest_agent/exporters/playwright_exporter.py`:
  - `class PlaywrightExporter`:
    - `__init__(self, env: jinja2.Environment)`.
    - `def export(self, case: TestCase, base_url: str | None = None) -> str` → returns full TS source.
    - Internal: iterate `case.steps`. For each, dispatch on `mcp_provider`:
      - `playwright-mcp` → use `_translate_playwright_step(step) -> str` which emits direct `page.*` calls. Map `mcp.browser.navigate(url=...)` → `await page.goto('...')`, `mcp.browser.click(selector=...)` → `await page.click('...')`, `mcp.browser.type(selector=, text=)` → `await page.fill(...)`, `mcp.browser.wait_for(selector=)` → `await expect(page.locator(...)).toBeVisible()`, `mcp.browser.eval(...)` → `await page.evaluate(...)`.
      - `api-http-mcp` → emit `const response = await request.fetch(url, {method, headers, body});` + assertion translation.
      - `postgres-mcp` → emit setup/teardown using `pg` client in `test.beforeAll`/`test.afterEach` hooks. Step body translated to inline `await pgClient.query('...')` calls in the test body.
      - `mysql-mcp` → similar but with `mysql2/promise`.
      - `mongo-mcp` → similar with `mongodb` driver.
      - `graphql-mcp` → emit `graphql-request` helper.
      - `grpc-mcp` → emit comment-only stub with `// TODO: gRPC step not natively supported by Playwright. Original code:\n// ...`.
      - `kubernetes-mcp` → similar comment-only stub OR helper if `@kubernetes/client-node` available.
      - other / unknown → comment stub.
    - Use `_extract_mcp_call(step.code)` to AST-parse the Python step code and extract the MCP tool name + args. Fall back to regex if AST parse fails.
- [ ] **15.2.3** Create Jinja2 template `packages/agent/src/suitest_agent/exporters/templates/playwright_test.ts.j2`:
  ```jinja
  import { test, expect, request } from '@playwright/test';
  {%- if uses_pg %}
  import { Client as PgClient } from 'pg';
  {%- endif %}
  {%- if uses_mongo %}
  import { MongoClient } from 'mongodb';
  {%- endif %}
  {%- if uses_mysql %}
  import mysql from 'mysql2/promise';
  {%- endif %}
  {%- if uses_graphql %}
  import { GraphQLClient } from 'graphql-request';
  {%- endif %}

  // Generated by Suitest from test case {{ case.public_id }} on {{ generated_at }}
  // Source mcp_providers: {{ providers_used | join(", ") }}
  {% if mixed_mcp %}
  // NOTE: This case uses multiple MCP providers. Non-browser steps are translated using helper clients.
  // Verify helper credentials in test.env or hardcoded fixtures.
  {% endif %}

  {% for hook in setup_hooks %}{{ hook }}{% endfor %}

  test('{{ case.name | tojson_inline }}', async ({ page }) => {
  {% for step_block in step_blocks %}
    // Step {{ loop.index }}: {{ step_block.action }}
    {{ step_block.code | indent(2) }}
  {% endfor %}
  });

  {% for hook in teardown_hooks %}{{ hook }}{% endfor %}
  ```

### 15.3 Endpoint

- [ ] **15.3.1** Add to `apps/api/src/suitest_api/routers/test_cases.py`:
  ```python
  @router.get("/{case_id}/export")
  async def export_case(
      case_id: str,
      target: Literal["playwright", "cypress", "selenium"] = "playwright",
      ctx: Annotated[RequestContext, Depends(require_role({"QA", "ADMIN", "OWNER"}))],
      svc: ExportService = Depends(),
  ) -> Response:
      code, filename = await svc.export(case_id, ctx.workspace_id, ctx.user_id, target)
      return Response(
          content=code,
          media_type="text/plain; charset=utf-8",
          headers={"Content-Disposition": f'attachment; filename="{filename}"'},
      )
  ```
- [ ] **15.3.2** `ExportService.export(case_id, workspace_id, user_id, target)`:
  - Load case with steps.
  - Pick exporter from registry (`{"playwright": PlaywrightExporter, "cypress": CypressExporter, "selenium": SeleniumExporter}`).
  - Run exporter → get code string.
  - Persist row in `code_exports` with `case_id, target, exported_code_text, user_id`.
  - Audit `code_export.created`.
  - Return `(code, f"{case.public_id}.spec.ts")`.

### 15.4 Tests

- [ ] **15.4.1** Add 3 fixture cases under `apps/api/tests/fixtures/cases/`:
  - `pure-fe.json` — 4 steps all `playwright-mcp` (navigate, click, fill, assert).
  - `pure-be.json` — 3 steps all `api-http-mcp` (POST login, GET resource, DELETE resource).
  - `mixed-mcp.json` — 5 steps: postgres (seed), api (login), playwright (UI), api (verify), postgres (verify) — the mixed-MCP checkout case.
- [ ] **15.4.2** Pytest `apps/api/tests/test_export_playwright.py`:
  - `test_export_pure_fe_snapshot` — POST cases load `pure-fe.json` → export → assert source contains `import { test, expect } from '@playwright/test'`, contains `await page.goto`, contains `await page.click`. Snapshot compare against `tests/snapshots/pure-fe.spec.ts.expected`.
  - `test_export_pure_be_snapshot` — assert contains `request.fetch`, no `page.` calls.
  - `test_export_mixed_snapshot` — assert contains both `await page.` and pgClient setup hooks; assert `// NOTE: This case uses multiple MCP providers` comment.
  - `test_export_persists_row` — verify `code_exports` row created.
  - `test_export_unknown_target_422` — `?target=invalid` → 422.
  - `test_export_unknown_case_404`.
  - `test_export_cross_workspace_404`.
  - `test_export_unauthenticated_401`.
  - `test_export_audit_logged`.
- [ ] **15.4.3** Smoke run the generated file in CI? Skip for unit test (Node + Playwright install heavy). Move to Task 22 DoD smoke.
- [ ] **15.4.4** Run tests. Green.
- [ ] **15.4.5** Commit: `feat(agent): Playwright code export (Closes #M2-12)`.

---

## Task 16: Test code export — Cypress target

### 16.1 Exporter module

- [ ] **16.1.1** Create `packages/agent/src/suitest_agent/exporters/cypress_exporter.py`:
  - `class CypressExporter`:
    - Similar shape to Playwright, but emits `describe()` + `it()` blocks.
    - `playwright-mcp` → `cy.visit`, `cy.get(...).click()`, `cy.get(...).type(...)`, `cy.contains(...)`.
    - `api-http-mcp` → `cy.request({method, url, body, headers})`.
    - Mixed-MCP non-browser steps (`postgres-mcp`, `mysql-mcp`, `mongo-mcp`, `graphql-mcp`, etc.) → `cy.task('db:exec', {sql, params})` / `cy.task('mongo:exec', {...})` placeholders. The exporter also emits a stub `cypress/plugins/db-task.js` snippet at the top of the file as a comment instructing user to wire the task.
    - `grpc-mcp`, `kubernetes-mcp` → comment stubs explaining limitation.
- [ ] **16.1.2** Jinja2 template `packages/agent/src/suitest_agent/exporters/templates/cypress_test.cy.ts.j2`:
  ```jinja
  /// <reference types="cypress" />
  // Generated by Suitest from test case {{ case.public_id }} on {{ generated_at }}
  {% if non_browser_steps %}
  // NOTE: This case uses non-browser MCP steps. Wire them via cypress/plugins/index.ts:
  //
  //   on('task', {
  //     'db:exec': async ({ sql, params }) => { /* your pg client here */ },
  //     'mongo:exec': async ({ op, args }) => { /* your mongo client here */ },
  //   })
  {% endif %}

  describe('{{ case.suite.name | default("Test Suite") }}', () => {
    it('{{ case.name }}', () => {
  {% for step_block in step_blocks %}
      // Step {{ loop.index }}: {{ step_block.action }}
      {{ step_block.code | indent(4) }}
  {% endfor %}
    });
  });
  ```

### 16.2 Tests

- [ ] **16.2.1** Pytest `apps/api/tests/test_export_cypress.py`:
  - `test_export_pure_fe_snapshot` — assert contains `describe`, `it`, `cy.visit`, `cy.get`. Snapshot.
  - `test_export_pure_be_snapshot` — contains `cy.request`.
  - `test_export_mixed_snapshot` — contains `cy.task('db:exec'` for postgres steps; contains the wiring comment block.
  - `test_export_grpc_step_emits_stub_comment` — assert comment with `// gRPC` text + original code preserved.
- [ ] **16.2.2** Run tests. Green.
- [ ] **16.2.3** Commit: `feat(agent): Cypress code export (Closes #M2-12)`.

---

## Task 17: Test code export — Selenium (pytest) target

### 17.1 Exporter module

- [ ] **17.1.1** Create `packages/agent/src/suitest_agent/exporters/selenium_exporter.py`:
  - `class SeleniumExporter`:
    - Emits Python `pytest` file using `selenium`, `webdriver-manager`, `pytest`, and `WebDriverWait` + `expected_conditions`.
    - `playwright-mcp` → `driver.find_element(By.CSS_SELECTOR, ...)`, `driver.get(...)`, `WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ...)))`.
    - `api-http-mcp` → `requests.request(method, url, headers=..., json=...)` + asserts.
    - `postgres-mcp` → `psycopg.connect(...)` in `@pytest.fixture(scope="module")` setup + teardown.
    - `mysql-mcp` → `pymysql.connect(...)`.
    - `mongo-mcp` → `pymongo.MongoClient`.
    - `graphql-mcp` → `gql` Python client.
    - `grpc-mcp` → comment stub.
    - `kubernetes-mcp` → `kubernetes` Python client.
- [ ] **17.1.2** Jinja2 template `packages/agent/src/suitest_agent/exporters/templates/selenium_test.py.j2`:
  ```jinja
  """
  Generated by Suitest from test case {{ case.public_id }} on {{ generated_at }}
  Mixed MCP providers used: {{ providers_used | join(", ") }}
  """
  from __future__ import annotations
  import pytest
  import requests
  from selenium import webdriver
  from selenium.webdriver.common.by import By
  from selenium.webdriver.support.ui import WebDriverWait
  from selenium.webdriver.support import expected_conditions as EC
  {%- if uses_pg %}
  import psycopg
  {%- endif %}
  {%- if uses_mongo %}
  from pymongo import MongoClient
  {%- endif %}

  {% for fixture in fixtures %}
  {{ fixture }}
  {% endfor %}

  def test_{{ case.public_id | replace("-", "_") | lower }}({{ fixture_params | join(", ") }}):
      """{{ case.name }}"""
  {% for step_block in step_blocks %}
      # Step {{ loop.index }}: {{ step_block.action }}
      {{ step_block.code | indent(4) }}
  {% endfor %}
  ```

### 17.2 Tests

- [ ] **17.2.1** Pytest `apps/api/tests/test_export_selenium.py`:
  - `test_export_pure_fe_snapshot` — contains `driver.get`, `WebDriverWait`, `By.CSS_SELECTOR`. Snapshot.
  - `test_export_pure_be_snapshot` — contains `requests.request`.
  - `test_export_mixed_snapshot` — contains `pg_fixture` fixture, `psycopg.connect`, plus selenium calls.
  - `test_export_snake_case_function_name` — `test_tc_1900` not `test_TC-1900`.
- [ ] **17.2.2** Run tests. Green.
- [ ] **17.2.3** Commit: `feat(agent): Selenium code export (Closes #M2-12)`.

---

## Task 18: Code export UI

UI dropdown + Monaco diff viewer + download.

### 18.1 Components

- [ ] **18.1.1** Update `apps/web/src/routes/(app)/cases/$caseId.tsx`:
  - Detail panel toolbar: add "Export" dropdown button (after "Run now").
  - Menu items: Playwright (TS) / Cypress (TS) / Selenium (Python).
  - Click → opens `<ExportPreviewModal>`.
- [ ] **18.1.2** Create `apps/web/src/components/cases/ExportPreviewModal.tsx`:
  - shadcn Dialog, `max-w-[1100px]`, `max-h-[90vh]`.
  - On open: `fetch('/api/v1/test-cases/:id/export?target=...')` → response text body.
  - Body: Monaco editor in read-only mode displaying the code (language auto-set: `typescript` for playwright/cypress, `python` for selenium).
  - Top-right of editor: copy-to-clipboard button + download button.
  - Download click: `Blob([code], {type: 'text/plain'})` → `URL.createObjectURL` → trigger anchor download with `case.public_id + '.spec.ts'` (or `.cy.ts` / `.py`).
  - Footer: warning banner for mixed-MCP cases ("This case uses multiple MCP providers. Non-browser steps emit helper-client placeholders — review before running.") computed by checking distinct `mcpProvider` count in `case.steps`.

### 18.2 Tests

- [ ] **18.2.1** Vitest `apps/web/src/components/cases/ExportPreviewModal.test.tsx`:
  - Mock fetch returning sample TS code → renders in Monaco (mock `@monaco-editor/react` as `<textarea>` for testability).
  - Click copy → navigator.clipboard.writeText called with code.
  - Click download → `URL.createObjectURL` called with Blob.
  - Mixed-MCP case → warning banner visible.
- [ ] **18.2.2** Playwright E2E `apps/web/e2e/code-export.spec.ts`:
  - Open case TC-1900 → click Export → Playwright → modal opens → code visible → download → assert file downloaded named `TC-1900.spec.ts`.
- [ ] **18.2.3** Run tests. Green.
- [ ] **18.2.4** Commit: `feat(web): code export preview + download UI (Closes #M2-12)`.

---

## Task 19: Generator UI — strategy gating in modal (ZERO finalization)

Ensures the modal locks AI-only and AI-enrich radios in ZERO and the E2E flow works strictly without LLM.

### 19.1 Gating fix-ups

- [ ] **19.1.1** In `StepStrategy.tsx` (Task 14.1.5), confirm:
  - `useCapabilities()` resolves tier.
  - When tier=`ZERO`: render AI-enrich and AI-only radios disabled with `<DisabledTooltip reason="Requires LLM. Settings → LLM">`.
  - Default selection: ZERO → `deterministic`, LOCAL/CLOUD → `ai_enrich`.
- [ ] **19.1.2** In `StepTargetPicker.tsx`, "Mixed PRD-driven" card disabled in ZERO with tooltip (matches UI_SPEC § 3.2.1.5).
- [ ] **19.1.3** Add upfront capability check in modal root: if user navigates to step 4 and selects AI strategy then back-revs to step 1 with a tier change (via WS `capability.changed` event), reset strategy to `deterministic` automatically + show toast.

### 19.2 E2E test

- [ ] **19.2.1** Playwright E2E `apps/web/e2e/generate-modal-zero-tier.spec.ts`:
  - Spin up app with `SUITEST_LLM_PROVIDER=none` env.
  - Login → Cases → click Generate split-button main → modal opens.
  - Step 1: assert "Backend API", "Frontend Web", "Database", "Infrastructure", "Custom MCP" enabled; "Mixed PRD-driven" disabled with tooltip text matched.
  - Click "Backend API" → step 2.
  - Paste OpenAPI URL of local httpbin fixture → next.
  - Step 3: assert `api-http-mcp` pre-selected, health pill green.
  - Step 4: only Deterministic radio enabled.
  - Step 5: SSE streams cases → ≥5 cases appear.
  - Uncheck 2, leave 3 → click "Add 3 to suite" → modal closes, toast "3 cases added".
  - Navigate back to Cases list → 3 new DRAFT cases visible.
- [ ] **19.2.2** Run E2E. Green.
- [ ] **19.2.3** Commit: `feat(web): ZERO-tier generation modal gating + E2E (Closes #M2-5)`.

---

## Task 20: SSE for generators (server side hardening)

All deterministic generators stream `progress` / `case` / `complete` / `error` events via SSE. Backend correctness + frontend consumption robustness.

### 20.1 SSE event types

- [ ] **20.1.1** Create `packages/shared/suitest_shared/schemas/generator_sse.py`:
  ```python
  from __future__ import annotations
  from datetime import datetime
  from enum import StrEnum
  from typing import Literal
  from pydantic import BaseModel
  from .generator_input import TestCaseDraft

  class GeneratorSseEventKind(StrEnum):
      PROGRESS = "progress"
      CASE = "case"
      COMPLETE = "complete"
      ERROR = "error"
      PING = "ping"

  class GeneratorProgress(BaseModel):
      stage: str
      message: str
      percent: float | None = None

  class GeneratorCaseEvent(BaseModel):
      draft_id: str
      case: TestCaseDraft
      seq: int

  class GeneratorCompleteEvent(BaseModel):
      generator_run_id: str
      total_generated: int
      duration_ms: int

  class GeneratorErrorEvent(BaseModel):
      code: str
      message: str
      details: dict[str, object] | None = None

  class GeneratorSseEvent(BaseModel):
      kind: GeneratorSseEventKind
      data: GeneratorProgress | GeneratorCaseEvent | GeneratorCompleteEvent | GeneratorErrorEvent | dict
      ts: datetime
  ```

### 20.2 SSE formatter helper

- [ ] **20.2.1** Create `apps/api/src/suitest_api/sse.py`:
  ```python
  import asyncio
  from collections.abc import AsyncIterator
  from suitest_shared.schemas.generator_sse import GeneratorSseEvent

  def format_sse(event: GeneratorSseEvent) -> bytes:
      payload = event.data.model_dump_json() if hasattr(event.data, "model_dump_json") else json.dumps(event.data)
      return f"event: {event.kind}\ndata: {payload}\n\n".encode()

  async def with_heartbeat(
      source: AsyncIterator[GeneratorSseEvent],
      interval_seconds: float = 15.0,
  ) -> AsyncIterator[bytes]:
      """Multiplex source events with periodic ping events."""
      next_event_task: asyncio.Task | None = None
      try:
          while True:
              if next_event_task is None:
                  next_event_task = asyncio.create_task(source.__anext__())
              try:
                  ev = await asyncio.wait_for(asyncio.shield(next_event_task), timeout=interval_seconds)
                  next_event_task = None
                  yield format_sse(ev)
              except asyncio.TimeoutError:
                  yield b"event: ping\ndata: {}\n\n"
              except StopAsyncIteration:
                  return
      finally:
          if next_event_task and not next_event_task.done():
              next_event_task.cancel()
  ```

### 20.3 Apply to all generators

- [ ] **20.3.1** Refactor `GeneratorService.run_openapi`, `run_crawler`, and recorder finalize so that they all return `AsyncIterator[GeneratorSseEvent]`. Each emits:
  - `progress` at major milestones (e.g., "Fetching spec…", "Parsing operations…", "Generating cases…", "Persisting drafts…").
  - `case` for each `TestCaseDraft` produced, with monotonic `seq`.
  - `complete` once at end with `generator_run_id`, `total_generated`, `duration_ms`.
  - `error` on exception (then close).
- [ ] **20.3.2** Apply `with_heartbeat` in router handlers so SSE responses include `event: ping` every 15s.

### 20.4 Tests

- [ ] **20.4.1** Pytest `apps/api/tests/test_generator_sse.py`:
  - Use `httpx-sse` client to consume the SSE stream from `/generators/openapi`.
  - `test_sse_emits_progress_then_cases_then_complete` — assert event order.
  - `test_sse_heartbeat_ping` — mock `with_heartbeat(interval_seconds=0.05)` short interval → consume for 0.2s → assert ≥3 ping events.
  - `test_sse_error_event_on_failure` — pass invalid spec → assert `event: error` emitted then stream closes.
  - `test_sse_strict_format` — parse bytes manually: each event has `event: X\ndata: Y\n\n` shape, no orphan lines.
- [ ] **20.4.2** Vitest `apps/web/src/lib/sse-post.test.ts`:
  - Mock streaming `Response.body` → parser yields correct event objects.
  - Heartbeat ping events are filtered before consumer callback (per design — UI doesn't care).
  - Malformed event chunk → parser skips, doesn't crash.
- [ ] **20.4.3** Run tests. Green.
- [ ] **20.4.4** Commit: `feat(api): SSE event schema + heartbeat for generators (Closes #M2-1 #M2-3)`.

---

## Task 21: Health check expansion for 5 new MCPs

Each new bundled provider implements `health()` per MCP_PLUGINS § 7. Probed every 60s by the existing background task from M1c.

### 21.1 Implementation

- [ ] **21.1.1** Verify each of `graphql.py`, `mongo.py`, `mysql.py`, `kubernetes.py`, `grpc.py` (from Tasks 5-9) implements `async def health(self) -> bool` per their respective probes (already declared above; this task is a cross-cutting verification).
- [ ] **21.1.2** Update `packages/mcp/src/suitest_mcp/health.py` background probe loop:
  - On startup, the loop pulls the union of bundled providers from `registry.list_bundled()` plus per-workspace custom providers.
  - For each: invoke `tools/list` with timeout 5s. Translate result:
    - Success + ≥1 tool returned + latency < 1s → `ok`.
    - Success but latency 1-5s → `degraded`.
    - Failure → `down`.
  - Persist to `mcp_providers.health_status` + `mcp_providers.last_health_at`.
  - Publish WS event `mcp.provider.health` with `{provider_id, name, status, latency_ms, error?}` on change.
- [ ] **21.1.3** Auto-disable threshold: provider `down` for >5 min → tag with `auto_disabled=true` in `config_json`. Re-enable on first `ok` probe.

### 21.2 Tests

- [ ] **21.2.1** Pytest `packages/mcp/tests/test_health_probes.py`:
  - Parametrized over each bundled provider:
    - `test_graphql_health_up` — testcontainer up → health=True.
    - `test_graphql_health_down` — point at port 0 → health=False.
    - `test_mongo_health_up`, `test_mongo_health_down`.
    - `test_mysql_health_up`, `test_mysql_health_down`.
    - `test_kubernetes_health_up`, `test_kubernetes_health_down`.
    - `test_grpc_health_up`, `test_grpc_health_down`.
  - `test_health_probe_loop_persists_state` — probe runs → DB row updated.
  - `test_health_probe_emits_ws_on_change` — mock Redis pub/sub → assert `mcp.provider.health` published.
  - `test_health_auto_disable_after_5min_down` — manually advance clock or set `last_health_at` to 6 min ago + status=down → assert `auto_disabled=true` set.
  - `test_health_re_enable_on_first_ok` — `auto_disabled=true` + next probe ok → flag cleared.
- [ ] **21.2.2** Run tests. Green.
- [ ] **21.2.3** Commit: `feat(mcp): health checks for 5 new bundled providers (Closes #M2-10)`.

---

## Task 22: DoD smoke test + tag release

Manual journey end-to-end + tag.

### 22.1 Smoke script

- [ ] **22.1.1** Create `scripts/m2_smoke.sh`:
  ```bash
  #!/usr/bin/env bash
  set -euo pipefail

  # Pre: docker compose up -d  (api + web + runner + pg + redis + minio)
  # Pre: SUITEST_LLM_PROVIDER=none  (ZERO tier)

  WORKSPACE_ID="ws_smoke_$(date +%s)"
  API="http://localhost:8000/api/v1"
  TOKEN="$(uv run python scripts/issue_test_token.py --workspace ${WORKSPACE_ID})"
  H="-H Authorization:Bearer ${TOKEN} -H X-Workspace-Id:${WORKSPACE_ID}"

  echo "== Step 1: verify ZERO tier =="
  TIER="$(curl -s ${API}/capabilities | jq -r .tier)"
  [[ "${TIER}" == "ZERO" ]] || { echo "FAIL: expected ZERO, got ${TIER}"; exit 1; }

  echo "== Step 2: register custom filesystem MCP =="
  PROVIDER_ID="$(curl -s ${H} -X POST ${API}/mcp/providers -d '{
    "name": "fs-mcp",
    "kind": "filesystem",
    "endpoint": "npx -y @modelcontextprotocol/server-filesystem /tmp",
    "transport": "stdio",
    "config": {},
    "secrets": {}
  }' -H 'Content-Type: application/json' | jq -r .id)"
  echo "Registered fs-mcp as ${PROVIDER_ID}"

  echo "== Step 3: generate cases from httpbin OpenAPI =="
  RESPONSE="$(curl -sN ${H} -X POST ${API}/generators/openapi -d '{
    "target_suite_id": "suite_smoke",
    "spec_url": "http://httpbin.local/openapi.json"
  }' -H 'Content-Type: application/json' -H 'Accept: text/event-stream')"
  CASE_COUNT="$(echo "${RESPONSE}" | grep -c '^event: case')"
  echo "Streamed ${CASE_COUNT} cases"
  [[ "${CASE_COUNT}" -ge 10 ]] || { echo "FAIL: expected ≥10 cases"; exit 1; }

  echo "== Step 4: save 8 of generated cases (POST batch) =="
  # ... (parse SSE response, pick first 8 drafts, POST /test-cases each)

  echo "== Step 5: run all 8 cases =="
  RUN_ID="$(curl -s ${H} -X POST ${API}/runs -d '{"selection":{"type":"suite","ids":["suite_smoke"]}}' -H 'Content-Type: application/json' | jq -r .id)"
  # Poll runs/:id until terminal
  while true; do
      STATUS="$(curl -s ${H} ${API}/runs/${RUN_ID} | jq -r .status)"
      [[ "${STATUS}" == "PASS" || "${STATUS}" == "FAIL" || "${STATUS}" == "ERROR" ]] && break
      sleep 2
  done
  [[ "${STATUS}" == "PASS" ]] || { echo "FAIL: run did not pass; status=${STATUS}"; exit 1; }

  echo "== Step 6: export top case to Playwright =="
  TOP_CASE_ID="$(curl -s ${H} ${API}/test-cases?suiteId=suite_smoke | jq -r .items[0].id)"
  curl -s ${H} "${API}/test-cases/${TOP_CASE_ID}/export?target=playwright" -o exported.spec.ts
  [[ -s exported.spec.ts ]] || { echo "FAIL: export empty"; exit 1; }
  grep -q "import { test" exported.spec.ts || { echo "FAIL: export missing imports"; exit 1; }

  echo "== Step 7: run exported file against local fixture =="
  pushd /tmp/m2-smoke-pw
  npm init -y > /dev/null
  npm install -D @playwright/test > /dev/null 2>&1
  npx playwright install chromium --with-deps > /dev/null 2>&1
  cp ${OLDPWD}/exported.spec.ts ./
  PLAYWRIGHT_BASE_URL=http://httpbin.local npx playwright test exported.spec.ts
  popd

  echo "== M2 smoke: ALL GREEN =="
  ```
- [ ] **22.1.2** Document smoke script in `examples/m2-smoke/README.md` with prerequisites and expected output.

### 22.2 Manual checklist

- [ ] **22.2.1** Verify `Suitest.html` mockup still matches generation modal screen for any visual regression.
- [ ] **22.2.2** Verify all 22 task commits squash into clean history.
- [ ] **22.2.3** Run `uv run mypy packages/agent/src packages/mcp/src apps/api/src apps/runner/src` clean.
- [ ] **22.2.4** Run `uv run ruff check . && uv run ruff format --check .` clean.
- [ ] **22.2.5** Run `cd apps/web && pnpm typecheck && pnpm lint && pnpm test` clean.
- [ ] **22.2.6** Run `make e2e` (Playwright E2E suite) — all M2 E2E specs green.
- [ ] **22.2.7** Run `pnpm exec axe` (a11y) on generation modal + MCP browser pages → no critical violations.

### 22.3 Tag

- [ ] **22.3.1** Update `CHANGELOG.md` with M2 features list.
- [ ] **22.3.2** Tag candidate `v0.6.0-m2` (annotated tag). Push tag.
- [ ] **22.3.3** Commit: `chore: release v0.6.0-m2 (M2 DoD smoke green)`.

---

## Cross-cutting verifications (run after every task ≥ green)

| Check | Command |
|-------|---------|
| Backend lint | `uv run ruff check .` |
| Backend format | `uv run ruff format --check .` |
| Backend types | `uv run mypy packages/agent/src packages/mcp/src apps/api/src apps/runner/src` |
| Backend tests | `uv run pytest -x --tb=short` |
| Frontend types | `pnpm --filter @suitest/web typecheck` |
| Frontend lint | `pnpm --filter @suitest/web lint` |
| Frontend tests | `pnpm --filter @suitest/web test` |
| E2E (after Task 14 onward) | `pnpm --filter @suitest/web e2e -- --grep m2` |
| DB migrations | `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head` |

---

## Definition of Done

All 22 tasks complete, every sub-step checkbox ticked, every test green in CI, smoke script returns "M2 smoke: ALL GREEN", and tag `v0.6.0-m2` pushed.

Operationally, a fresh ZERO-tier deploy must be able to:

1. Register a custom MCP without code changes.
2. Classify any input (URL / file / text) deterministically.
3. Generate cases from OpenAPI, from a recorded browser session, or from a heuristic URL crawl — all without any LLM call.
4. Run the mixed-MCP Checkout E2E demo case and observe each step routed to its declared MCP provider.
5. Export any of the 18 seed cases + the 100+ generated cases to Playwright, Cypress, or Selenium.
6. Show health pill green for all 8 bundled MCP providers (`playwright-mcp`, `api-http-mcp`, `postgres-mcp`, `graphql-mcp`, `mongo-mcp`, `mysql-mcp`, `kubernetes-mcp`, `grpc-mcp`).
7. Persist `routing_overrides` per workspace and have the runner respect them.

No LLM call is made anywhere — verify by inspecting LiteLLM invocation count in observability dashboard (should be zero) and `capabilities.tier === "ZERO"` throughout.

---

## Notes & rationale for design decisions

1. **Generators live in `packages/agent`, not `packages/generators`.** Both deterministic and LLM-driven generators share a discovery surface (the `Generator` Protocol from GENERATORS.md § 12 in v1.x). Putting them in a single package now avoids a future move. Subdirectory split (`generators/` vs future `graphs/`) keeps boundaries clear.

2. **Kubernetes uses in-process `kubernetes_asyncio` not stdio.** MCP_PLUGINS.md describes some providers as "stdio subprocess wrappers" but our v1.0 implementation prefers Python in-process clients where they exist (graphql, mongo, mysql, kubernetes) — same MCP server contract from the runner's perspective, but lighter resource footprint and no subprocess lifecycle to manage. We retain stdio for grpc only because the gRPC reflection client wiring is cleaner in a separate process with proto cache. This is a deliberate departure from the doc's prescriptive transport column; the doc's `transport` field is for the contract surface, not the implementation detail of how Suitest wraps it. Update MCP_PLUGINS.md § 3 in a docs PR after M2 to clarify.

3. **Recorder events stored as JSONB rather than separate table.** `recorder_sessions.captured_events_json` is a list of `RecorderEvent` rows. We avoid a child `recorder_events` table because lifetime ≤ 30 min and access pattern is "load all events then convert to case". JSONB performance is adequate for the expected event volume (< 1000 events per session).

4. **Code export is fully deterministic.** Unlike the AI exporters discussed in v1.x roadmap, M2's exporters are 1:1 mappings via Jinja2 + AST parsing of `step.code`. This guarantees ZERO-tier availability and reproducibility. Complex providers (grpc, kubernetes) produce documented comment stubs rather than partial translations.

5. **Mixed-MCP case in seed is hard-coded `TC-1900` reserved ID.** Avoids collision with auto-incrementing public_id sequence. Adjust if M1a public_id sequence was already past 1900 — pick next free range. The seed migration is idempotent regardless.

6. **SSE heartbeat is per-stream, not global.** Each generator response opens its own heartbeat task. This is simpler and avoids cross-stream interference; cost is a per-request `asyncio.Task` for the heartbeat, negligible.

7. **`api-http-mcp` is in-process from M1c.** Not re-implemented in M2. The new in-process providers (graphql, mongo, mysql) follow the same `BundledProvider` interface for consistency.

8. **No `mcp-discovery` LLM-driven generator in M2.** That's M3 work. Custom MCP registration + tool browser are deterministic (just `tools/list` and JSON-schema form rendering) and shipped here.

9. **Code export persists in `code_exports` table for audit traceability.** Even though the export is deterministic and could be regenerated, having a row per export gives downstream queries (e.g., "show me everyone who exported case X this week") and supports the v1.x Eval UI that needs export history.

10. **Strategy 4 in the generation modal "is in M2 by virtue of being the default + only choice in ZERO".** Task 19 hardens the gating so AI strategies remain visible-but-disabled (per UI_SPEC) rather than hidden, preserving the upgrade-discoverability principle.

---

End of M2 plan. Implementation order: Task 0 → 1 → 2 → 3 → 4 (TCM generators backend) → 5 → 6 → 7 → 8 → 9 (bundled MCPs) → 10 → 11 (custom MCP CRUD + UI) → 12 (routing) → 13 (mixed-MCP demo) → 14 → 15 → 16 → 17 → 18 (UI + export) → 19 (modal gating polish) → 20 (SSE hardening) → 21 (health) → 22 (DoD smoke + tag).

Subagent-driven workers may pick up Tasks 5–9 (bundled MCPs) in parallel after Task 0 lands; Tasks 15–17 (code export per framework) are likewise parallelizable after Task 14 lands. Tasks 2 (OpenAPI) and 3 (Crawler) can run in parallel once Task 1 (classifier) is merged.
