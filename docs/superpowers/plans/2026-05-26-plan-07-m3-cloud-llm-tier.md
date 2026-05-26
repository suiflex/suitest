# M3 — CLOUD LLM Tier Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Activate CLOUD LLM tier by integrating LiteLLM (multi-provider router) and LangGraph (state machine orchestrator) under `packages/agent`. Implement 4 agent modes (GENERATION/EXECUTION/DIAGNOSIS/CONVERSATION), 4 LLM-driven generation sources (PRD, URL semantic, MCP discovery, OpenAPI enrich), action→code runtime translation during execution, AI diagnosis on run failure, conversation-mode AI panel in UI, 4 autonomy levels with per-feature overrides, Settings → LLM and Settings → Automation pages, encrypted API key storage, prompt versioning, full reproducibility metadata persistence, and cost tracking with budget guard.

**Architecture:** `packages/agent/suitest_agent/providers/litellm_router.py` wraps LiteLLM `acompletion` with workspace-scoped client (model + provider resolved from `llm_configs` row, key decrypted via `packages/core/crypto`). LangGraph state machines per mode live in `packages/agent/suitest_agent/graphs/`, each with checkpointer backed by `langgraph-checkpoint-postgres` for resumability. Tier+autonomy guards via FastAPI dependencies `require_tier(Tier.CLOUD|Tier.LOCAL)` and `require_autonomy(AutonomyLevel.ASSIST)`. Streaming: SSE for token deltas + WebSocket for tool-call events. Cost tracking via `litellm.completion_cost()` recorded on `agent_sessions.cost_usd`. Reproducibility: every session persists `prompt_version_id`, `model_id`, `provider`, `seed`, `temperature`, full message log, tool call trace.

**Tech Stack:** Python 3.12, FastAPI, LiteLLM 1.50+, LangGraph 0.2+, langgraph-checkpoint-postgres, OpenAPI-driven LLM tool schemas (Pydantic v2), `cryptography` AES-GCM (from M1a packages/core/crypto), pytest-asyncio, VCR.py for LLM cassettes, mock provider for deterministic tests. FE: `@ai-sdk/react`, `assistant-ui`, EventSource, native WebSocket.

---

## Prerequisites

Before starting M3, verify:

- **M0** complete — monorepo, Docker compose, FastAPI + Vite boot, FastAPI-Users auth wired, base Alembic migrations applied, `GET /capabilities` → ZERO.
- **M1a** complete — DB schema (workspaces, projects, suites, test_cases, test_steps, runs, run_steps, artifacts, defects, requirements, integrations, audit_logs, agent_sessions, agent_messages, agent_tool_calls, mcp_providers, llm_configs, workspace_capabilities, prompt_versions, eval_runs, generator_runs, code_exports), AES-GCM crypto helper at `packages/core/suitest_core/crypto.py`, audit log helper, full seed (`Nusantara Retail` workspace, 1 project, 4 suites, 18 cases, 5 runs, 3 defects, 6 requirements, 8 integrations).
- **M1b** complete — read-only UI screens with `<Gated>`, `<TierBadge>`, `<McpProviderPill>`, `<AutonomyIndicator>`, `<DisabledTooltip>`, `<DisabledPlaceholder>`, `<CostChip>` shared components present (placeholder/empty impl OK for those that depend on M3). `useCapabilities()` Zustand store reading from `GET /capabilities`. AiPanel placeholder hidden in ZERO.
- **M1c** complete — `packages/mcp` registry + client + invoker + routing + health probe; 3 bundled MCPs (`playwright-mcp`, `api-http-mcp`, `postgres-mcp`); ARQ worker pulls run jobs and dispatches per-step via `step.mcp_provider`; step executor SKIPs no-code steps in ZERO with reason `NO_LLM_FOR_AGENTIC_STEP` and the LOCAL/CLOUD branch currently emits `TODO(M3): agentic translate not yet implemented` — that branch is rewired by **Task 12**.
- **M1d** complete — Test case CRUD writes, suite CRUD, manual defect creation, **rule-based** auto-defect filing (`agent_diagnosis_kind = MANUAL_TRIAGE` with deterministic categorizer); Jira/Linear/GitHub adapters; Slack notifications; GitHub webhook trigger.
- **M2** complete — 3 deterministic generators (OpenAPI, Recorder, Heuristic crawler), target classifier (rule-based), 8 bundled MCPs (M1c × 3 + `graphql-mcp`, `mongo-mcp`, `mysql-mcp`, `kubernetes-mcp`, `grpc-mcp`), custom MCP registration end-to-end, mixed-MCP test case execution proven, code export to Playwright/Cypress/Selenium.
- **No LLM call has ever been made** by the codebase — M3 introduces the very first LLM invocation pathway.

If any prerequisite is missing, stop and complete that milestone first.

---

## Conventions for this plan

- **TDD always.** Each backend task: (1) write failing pytest, (2) implement minimal code, (3) green, (4) refactor, (5) commit. Each FE task: vitest unit + Playwright E2E where the flow is observable. Tests run in CI per task before commit.
- **Conventional commits per sub-step** with milestone reference: `feat(agent): wire LiteLLM router (Closes #M3-1)`, `feat(api): /workspaces/:id/llm-config (Closes #M3-2)`, etc. Multiple sub-step commits per task are encouraged; each commit must leave CI green.
- **Pydantic v2** everywhere for API I/O. Domain models in `packages/shared/suitest_shared/schemas/`. SQLAlchemy 2.0 async ORM in `packages/db/suitest_db/models/`. Configure `model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True, populate_by_name=True)`.
- **mypy strict** with `disallow_untyped_defs=true`. No `Any` — use `TypedDict`, `Protocol`, generics. No `as any` in TypeScript.
- **No barrel files.** Direct imports only.
- **Capability gate** — every new endpoint declares `Depends(require_tier(...))`. LLM-touching endpoints declare `require_tier(Tier.CLOUD | Tier.LOCAL)`. Endpoints that mutate via agent action declare additional `require_autonomy(AutonomyLevel.ASSIST)`. `Settings → LLM` endpoints intentionally accept ZERO (that's the way users upgrade out of ZERO).
- **Audit log** every mutation through `packages/db/audit.py::write_audit`. LLM config changes, autonomy changes, agent sessions started/completed, agent-initiated mutations (`cases.create`, `defect.create`, `tracker.create_issue`) all emit `audit_logs` rows with `actor_type='agent'`, `correlation_id=agent_session_id`, `autonomy_level_at_time`, `before/after` snapshots.
- **VCR.py cassettes** for every real LLM call test. Cassettes live in `packages/agent/tests/cassettes/<provider>/<test_name>.yaml`. **Scrubbed** by a VCR filter that strips `Authorization`, `api-key`, `x-api-key`, AWS signing headers. Real recording is admin-only via `pytest --record-mode=once -m vcr_record`; default CI replays only.
- **Mock provider** is the default for unit tests. Set `SUITEST_LLM_PROVIDER=mock` to short-circuit LiteLLM. Mock returns canned responses keyed by sha256 of the input prompt+tool-schema, raises `MockProviderUnknownInputError` for unknown inputs to keep tests deterministic.
- **SSE format** strict per W3C spec — each event has `event: <name>\ndata: <json>\n\n`. Use FastAPI `StreamingResponse(generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})`. Heartbeat every 15s.
- **OpenTelemetry** — wrap every graph invocation in a span named `agent.session.<mode>` with attrs `agent.mode`, `agent.model`, `agent.provider`, `agent.workspace_id`, `agent.tier`, `agent.autonomy`, `agent.prompt_version_id`. Each LLM call gets a nested `agent.llm_call` span with `llm.tokens_in`, `llm.tokens_out`, `llm.cost_usd`, `llm.duration_ms`.
- **Reproducibility** — every `AgentSession` row at the moment of creation persists: `provider`, `model_id`, `prompt_version_id`, `seed`, `temperature`, `metadata_json` (request payload incl. autonomy/tier snapshot). Every LLM round-trip appends `AgentMessage` rows; every tool call appends `AgentToolCall` rows. `metadata_json` on the session also captures the `rag_chunks` array (chunk ids + content hashes) when retrieval ran.
- **Workspace scoping** is mandatory — every service method takes `workspace_id` as first business param. Cross-workspace access returns 404 (never 403, to avoid tenant enumeration).
- **Streaming cancellation** — every graph receives an `asyncio.Event` via contextvar `cancel_event`. Graph nodes check it between LLM calls and tool calls; abort raises `AgentCancelled` which is translated to SSE `event: agent.session.cancelled`.
- **Frontend mutations** — TanStack Query `useMutation` with optimistic snapshot + rollback. Streaming consumed via `@ai-sdk/react` for tokens + native WebSocket for tool/approval events.
- **Pre-commit gates** — `ruff format` / `ruff check` / `mypy --strict` / `pytest -x` must pass before each commit. FE: `tsc --noEmit` / `eslint` / `vitest run`.
- **ZERO-tier regression guard** — every backend task includes at least one test that boots a workspace at ZERO tier and asserts the M3 surface returns `503 LLM_DISABLED` or stays no-op as documented. M2 + M1 functionality is **never** allowed to break.

---

## Task 0: Migration prep — agent reproducibility columns + autonomy audit

The DB schema for M3 is largely in place from M1a (see DATA_MODEL.md §3.9 + §4) — this task only fills gaps and adds indexes / check constraints discovered during M3 implementation.

- [ ] **0.1** Run `uv run alembic heads` and `uv run alembic history --indicate-current`. Capture current head SHA.
- [ ] **0.2** Create migration `packages/db/suitest_db/migrations/versions/2026_05_26_m3_agent_repro_and_budget.py`:
  - `revision = "m3_agent_repro_and_budget"`
  - `down_revision = "<current head>"`
  - `upgrade()`:
    - Verify columns from M1a on `agent_sessions`: `provider TEXT NOT NULL`, `prompt_version_id TEXT NULL REFERENCES prompt_versions(id)`, `seed INTEGER NULL`, `temperature DOUBLE PRECISION NULL`, `cost_usd NUMERIC(10,4) NULL`. If any missing → `op.add_column(...)`.
    - Verify `agent_tool_calls.mcp_provider TEXT NULL` exists. If missing → add.
    - Add `agent_sessions.cancel_requested_at TIMESTAMPTZ NULL` (used by cancellation flow in Task 7 + 15).
    - Add `agent_sessions.rag_chunks_json JSONB NOT NULL DEFAULT '[]'::jsonb` (reproducibility — list of `{chunk_id, content_sha256}`).
    - Add `agent_sessions.tool_call_trace_json JSONB NOT NULL DEFAULT '[]'::jsonb` (denormalized ordered list — fast replay without join).
    - Add check constraint `ck_agent_sessions_cost_nonneg CHECK (cost_usd IS NULL OR cost_usd >= 0)`.
    - Add index `ix_agent_sessions_cost ON agent_sessions(workspace_id, started_at) WHERE cost_usd IS NOT NULL` for cost aggregation queries.
    - Create new table `agent_autonomy_audit`:
      ```sql
      CREATE TABLE agent_autonomy_audit (
        id            TEXT PRIMARY KEY,
        workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        actor_user_id UUID NULL REFERENCES users(id),
        actor_type    TEXT NOT NULL CHECK (actor_type IN ('user','system','agent')),
        level_before  TEXT NOT NULL,
        level_after   TEXT NOT NULL,
        overrides_before JSONB NOT NULL DEFAULT '{}'::jsonb,
        overrides_after  JSONB NOT NULL DEFAULT '{}'::jsonb,
        reason        TEXT NULL,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
      );
      CREATE INDEX ix_agent_autonomy_audit_workspace_created ON agent_autonomy_audit(workspace_id, created_at DESC);
      ```
    - Create new table `workspace_budgets` (used by Task 21):
      ```sql
      CREATE TABLE workspace_budgets (
        workspace_id  TEXT PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
        daily_usd     NUMERIC(10,2) NOT NULL DEFAULT 5.00,
        monthly_usd   NUMERIC(10,2) NOT NULL DEFAULT 100.00,
        soft_cap_pct  NUMERIC(4,3)  NOT NULL DEFAULT 0.800,
        hard_cap_pct  NUMERIC(4,3)  NOT NULL DEFAULT 1.000,
        downgrade_map_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
      );
      ```
    - Create new table `autonomy_configs` (one row per workspace — separates the dial from the materialized `workspace_capabilities` snapshot):
      ```sql
      CREATE TABLE autonomy_configs (
        workspace_id  TEXT PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
        level         TEXT NOT NULL DEFAULT 'manual' CHECK (level IN ('manual','assist','semi_auto','auto')),
        overrides_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        updated_by_user_id UUID NULL REFERENCES users(id),
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
      );
      ```
  - `downgrade()` mirror-drops everything `upgrade()` added.
- [ ] **0.3** Write pytest `packages/db/tests/test_migration_m3.py`:
  - Apply migration → inspector reports `agent_autonomy_audit`, `workspace_budgets`, `autonomy_configs` tables present with expected columns + indexes.
  - Insert a row into each new table, assert constraints (negative cost rejected; bad `level` rejected).
  - Downgrade → tables gone, columns reverted.
- [ ] **0.4** `uv run alembic upgrade head` against dev DB.
- [ ] **0.5** Add ORM models in `packages/db/suitest_db/models/`:
  - `agent_autonomy_audit.py` → `class AgentAutonomyAudit(Base): __tablename__ = "agent_autonomy_audit"` with mapped columns matching schema above.
  - `workspace_budget.py` → `class WorkspaceBudget(Base): __tablename__ = "workspace_budgets"`.
  - `autonomy_config.py` → `class AutonomyConfig(Base): __tablename__ = "autonomy_configs"`.
  - Update `agent_session.py` (already in M1a) to add `cancel_requested_at`, `rag_chunks_json`, `tool_call_trace_json` fields if missing.
- [ ] **0.6** Repositories under `packages/db/suitest_db/repositories/`:
  - `autonomy_repo.py`: `get_by_workspace`, `upsert`, `audit_history`.
  - `budget_repo.py`: `get_by_workspace`, `upsert`, `sum_cost_today(workspace_id)`, `sum_cost_month(workspace_id)`.
  - `agent_session_repo.py` (extend if exists): `create`, `mark_completed`, `update_cost`, `append_message`, `append_tool_call`, `cancel_requested`, `get_with_messages`.
- [ ] **0.7** Repository unit tests `packages/db/tests/test_repos_m3.py`. Cover happy + cross-workspace 404 + constraint violation paths for each method.
- [ ] **0.8** Commit: `feat(db): add autonomy_configs, agent_autonomy_audit, workspace_budgets, repro columns (Closes #M3-0)`.

---

## Task 1: LiteLLM router foundation

The single chokepoint through which **every** LLM call passes. No other module imports `litellm` directly.

### 1.1 Dependencies

- [ ] **1.1.1** Update `packages/agent/pyproject.toml`:
  ```toml
  [project]
  name = "suitest-agent"
  requires-python = ">=3.12"
  dependencies = [
    "litellm>=1.50,<2.0",
    "langgraph>=0.2,<0.3",
    "langgraph-checkpoint-postgres>=2.0,<3.0",
    "pydantic>=2.7,<3.0",
    "sqlalchemy[asyncio]>=2.0,<3.0",
    "asyncpg>=0.29",
    "pgvector>=0.3",
    "mcp>=1.0",
    "opentelemetry-api>=1.27",
    "opentelemetry-sdk>=1.27",
    "structlog>=24.1",
    "httpx>=0.27",
    "tenacity>=8.2",
  ]
  [project.optional-dependencies]
  dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "vcrpy>=6.0",
    "respx>=0.21",
    "freezegun>=1.4",
  ]
  ```
- [ ] **1.1.2** `uv lock` + `uv sync` cleanly resolves. Commit lockfile.

### 1.2 Settings + secret loading

- [ ] **1.2.1** Create `packages/agent/src/suitest_agent/providers/settings.py`:
  ```python
  from __future__ import annotations
  from typing import Literal
  from pydantic import BaseModel, ConfigDict, Field, SecretStr

  ProviderName = Literal[
      "mock", "none",
      "anthropic", "openai", "gemini", "groq", "openrouter",
      "azure", "bedrock", "vertex", "deepseek",
      "ollama", "llamacpp", "vllm", "lmstudio",
  ]

  class LiteLLMProviderConfig(BaseModel):
      model_config = ConfigDict(frozen=True, str_strip_whitespace=True)
      provider: ProviderName
      model: str = Field(..., min_length=1)
      api_key: SecretStr | None = None
      base_url: str | None = None
      timeout_ms: int = 60_000
      max_retries: int = 2
      # Anthropic prompt-caching toggle; ignored by providers that don't support it.
      cache_control: bool = True
      # AWS Bedrock / Vertex specific
      aws_region: str | None = None
      gcp_project: str | None = None
      gcp_location: str | None = None
      gcp_credentials_path: str | None = None
  ```
- [ ] **1.2.2** Test `packages/agent/tests/providers/test_settings.py` — assert `SecretStr` masks key on `repr()` and `model_dump()` (default `mode="python"` keeps it `SecretStr`; `mode="json"` rejects via custom serializer). One test for each known provider name accepted; unknown rejected.

### 1.3 Router class

- [ ] **1.3.1** Create `packages/agent/src/suitest_agent/providers/litellm_router.py`:
  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from decimal import Decimal
  from typing import AsyncIterator, TYPE_CHECKING
  import asyncio, os, time

  import litellm
  from litellm import acompletion, completion_cost
  import structlog
  from opentelemetry import trace

  from suitest_agent.providers.settings import LiteLLMProviderConfig

  if TYPE_CHECKING:
      from litellm.types.utils import ModelResponse

  log = structlog.get_logger(__name__)
  tracer = trace.get_tracer("suitest.agent.litellm")

  # Global LiteLLM config — applied once on first router init.
  _GLOBAL_INIT_DONE = False

  def _global_init() -> None:
      global _GLOBAL_INIT_DONE
      if _GLOBAL_INIT_DONE:
          return
      litellm.set_verbose = False
      litellm.drop_params = True
      litellm.suppress_debug_info = True
      litellm.telemetry = False
      _GLOBAL_INIT_DONE = True


  @dataclass(frozen=True)
  class CompletionResult:
      content: str
      tool_calls: list[dict]
      tokens_in: int
      tokens_out: int
      cost_usd: Decimal
      model: str
      provider: str
      duration_ms: int
      raw_response: object   # litellm ModelResponse


  class LiteLLMRouter:
      """Workspace-scoped LiteLLM wrapper. Single object per (workspace_id, llm_config_version)."""

      def __init__(self, cfg: LiteLLMProviderConfig):
          _global_init()
          self.cfg = cfg
          self._litellm_model = self._resolve_model_id(cfg)

      @staticmethod
      def _resolve_model_id(cfg: LiteLLMProviderConfig) -> str:
          # LiteLLM expects "anthropic/claude-sonnet-4-5", "openai/gpt-4o", "ollama/llama3.1", …
          prefixes = {
              "anthropic": "anthropic", "openai": "openai", "gemini": "gemini",
              "groq": "groq", "openrouter": "openrouter", "deepseek": "deepseek",
              "azure": "azure", "bedrock": "bedrock", "vertex": "vertex_ai",
              "ollama": "ollama", "llamacpp": "openai", "vllm": "openai",
              "lmstudio": "openai",
          }
          if cfg.provider == "mock":
              return f"mock/{cfg.model}"
          return f"{prefixes[cfg.provider]}/{cfg.model}"

      def _build_kwargs(self, messages: list[dict], *, temperature: float, max_tokens: int,
                        tools: list[dict] | None, seed: int | None, stream: bool) -> dict:
          kw: dict[str, object] = dict(
              model=self._litellm_model,
              messages=messages,
              temperature=temperature,
              max_tokens=max_tokens,
              stream=stream,
              timeout=self.cfg.timeout_ms / 1000,
              num_retries=self.cfg.max_retries,
          )
          if tools:
              kw["tools"] = tools
          if seed is not None:
              kw["seed"] = seed
          # API key — LiteLLM accepts `api_key=` direct kwarg per call.
          if self.cfg.api_key is not None:
              kw["api_key"] = self.cfg.api_key.get_secret_value()
          if self.cfg.base_url:
              kw["api_base"] = self.cfg.base_url
          # Anthropic prompt caching: caller is expected to set `cache_control` blocks on messages.
          # Bedrock
          if self.cfg.provider == "bedrock" and self.cfg.aws_region:
              kw["aws_region_name"] = self.cfg.aws_region
          # Vertex
          if self.cfg.provider == "vertex":
              if self.cfg.gcp_project:
                  kw["vertex_project"] = self.cfg.gcp_project
              if self.cfg.gcp_location:
                  kw["vertex_location"] = self.cfg.gcp_location
              if self.cfg.gcp_credentials_path:
                  os.environ.setdefault(
                      "GOOGLE_APPLICATION_CREDENTIALS", self.cfg.gcp_credentials_path,
                  )
          return kw

      async def complete(
          self,
          *, messages: list[dict],
          temperature: float = 0.2,
          max_tokens: int = 4096,
          tools: list[dict] | None = None,
          seed: int | None = None,
      ) -> CompletionResult:
          t0 = time.perf_counter()
          with tracer.start_as_current_span("agent.llm_call") as span:
              span.set_attributes({"llm.provider": self.cfg.provider, "llm.model": self.cfg.model})
              kw = self._build_kwargs(messages, temperature=temperature, max_tokens=max_tokens,
                                      tools=tools, seed=seed, stream=False)
              resp = await acompletion(**kw)
              dur = int((time.perf_counter() - t0) * 1000)
              choice = resp.choices[0]
              content = choice.message.content or ""
              tool_calls = [
                  {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                  for tc in (choice.message.tool_calls or [])
              ]
              cost = Decimal(str(completion_cost(completion_response=resp) or 0))
              span.set_attributes({
                  "llm.tokens_in": resp.usage.prompt_tokens,
                  "llm.tokens_out": resp.usage.completion_tokens,
                  "llm.cost_usd": float(cost),
                  "llm.duration_ms": dur,
              })
              return CompletionResult(
                  content=content, tool_calls=tool_calls,
                  tokens_in=resp.usage.prompt_tokens,
                  tokens_out=resp.usage.completion_tokens,
                  cost_usd=cost, model=self.cfg.model, provider=self.cfg.provider,
                  duration_ms=dur, raw_response=resp,
              )

      async def stream(
          self,
          *, messages: list[dict],
          temperature: float = 0.2,
          max_tokens: int = 4096,
          tools: list[dict] | None = None,
          seed: int | None = None,
      ) -> AsyncIterator[dict]:
          """Yield normalized chunks: {type, content_delta?, tool_call_delta?, finish_reason?}."""
          kw = self._build_kwargs(messages, temperature=temperature, max_tokens=max_tokens,
                                  tools=tools, seed=seed, stream=True)
          async for chunk in await acompletion(**kw):
              delta = chunk.choices[0].delta
              if delta.content:
                  yield {"type": "content", "content_delta": delta.content}
              for tc in (delta.tool_calls or []):
                  yield {
                      "type": "tool_call",
                      "tool_call_id": tc.id,
                      "tool_name": tc.function.name if tc.function else None,
                      "arguments_delta": tc.function.arguments if tc.function else "",
                  }
              if chunk.choices[0].finish_reason:
                  yield {"type": "finish", "reason": chunk.choices[0].finish_reason}

      async def health_check(self) -> tuple[bool, int, str | None]:
          """Returns (ok, latency_ms, error_msg)."""
          t0 = time.perf_counter()
          try:
              await self.complete(
                  messages=[{"role": "user", "content": "health-check"}],
                  max_tokens=8, temperature=0,
              )
              return True, int((time.perf_counter() - t0) * 1000), None
          except Exception as exc:
              return False, int((time.perf_counter() - t0) * 1000), str(exc)
  ```
- [ ] **1.3.2** Provider-specific helpers in same file:
  - `def anthropic_cache_block(content: str) -> dict` returning `{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}`. Used by prompt builders for system + RAG chunks.
  - `def bedrock_credentials_present() -> bool` — checks `AWS_ACCESS_KEY_ID` env or IAM role available.

### 1.4 Provider registry / factory

- [ ] **1.4.1** Create `packages/agent/src/suitest_agent/providers/factory.py`:
  ```python
  from __future__ import annotations
  from typing import Annotated
  from fastapi import Depends, HTTPException
  from sqlalchemy.ext.asyncio import AsyncSession

  from suitest_agent.providers.litellm_router import LiteLLMRouter
  from suitest_agent.providers.settings import LiteLLMProviderConfig
  from suitest_agent.providers.mock import MockRouter      # Task 2
  from suitest_core.crypto import decrypt
  from suitest_db.repositories.llm_config_repo import get_active_llm_config

  async def build_router_for_workspace(
      workspace_id: str, *, db: AsyncSession,
  ) -> LiteLLMRouter | MockRouter:
      cfg_row = await get_active_llm_config(db, workspace_id)
      if cfg_row is None or cfg_row.provider in ("none", "mock"):
          if cfg_row and cfg_row.provider == "mock":
              return MockRouter(model=cfg_row.model)
          raise HTTPException(
              status_code=503,
              detail={"error": {"code": "LLM_DISABLED",
                                "message": "Configure an LLM provider in Settings → LLM."}},
          )
      api_key = decrypt(cfg_row.api_key_encrypted) if cfg_row.api_key_encrypted else None
      cfg = LiteLLMProviderConfig(
          provider=cfg_row.provider, model=cfg_row.model,
          api_key=api_key, base_url=(cfg_row.config_json or {}).get("base_url"),
          timeout_ms=(cfg_row.config_json or {}).get("timeout_ms", 60_000),
          aws_region=(cfg_row.config_json or {}).get("aws_region"),
          gcp_project=(cfg_row.config_json or {}).get("gcp_project"),
          gcp_location=(cfg_row.config_json or {}).get("gcp_location"),
          gcp_credentials_path=(cfg_row.config_json or {}).get("gcp_credentials_path"),
      )
      return LiteLLMRouter(cfg)
  ```

### 1.5 Tests with VCR cassettes

- [ ] **1.5.1** Create `packages/agent/tests/providers/conftest.py`:
  ```python
  import vcr, pytest
  from pathlib import Path

  @pytest.fixture(scope="module")
  def vcr_config():
      return vcr.VCR(
          cassette_library_dir=str(Path(__file__).parent / "cassettes"),
          filter_headers=["authorization", "api-key", "x-api-key",
                          "x-amz-security-token", "x-goog-api-key"],
          filter_post_data_parameters=["api_key"],
          decode_compressed_response=True,
          record_mode="none",        # CI default — strict replay
      )
  ```
- [ ] **1.5.2** Write `packages/agent/tests/providers/test_litellm_router.py` covering:
  - `test_anthropic_complete_returns_cost_and_tokens` — replay `cassettes/anthropic/complete_basic.yaml`. Assert `result.tokens_in > 0`, `result.cost_usd > 0`, `result.provider == "anthropic"`.
  - `test_openai_complete_returns_tool_calls` — replay `cassettes/openai/tool_use_basic.yaml`. Assert one tool call decoded.
  - `test_gemini_complete_basic` — replay `cassettes/gemini/complete_basic.yaml`.
  - `test_groq_complete_basic` — replay `cassettes/groq/complete_basic.yaml`.
  - `test_openrouter_complete_basic` — replay `cassettes/openrouter/complete_basic.yaml`.
  - `test_anthropic_stream_yields_deltas` — replay `cassettes/anthropic/stream_basic.yaml`. Assert ≥1 chunk with `type=="content"`.
  - `test_bedrock_requires_aws_creds` — assert raises if `aws_region` set but no AWS creds (skipped in CI w/o creds).
  - `test_drop_params_silently_drops_seed_for_anthropic` — assert no exception when `seed=42` passed.
  - `test_health_check_returns_latency_and_ok` — replay `cassettes/anthropic/health_basic.yaml`.
- [ ] **1.5.3** Provide one canned VCR cassette per provider listed above with synthetic content (small response, deterministic). All cassettes scrubbed.
- [ ] **1.5.4** `uv run pytest packages/agent/tests/providers/ -x -m vcr` green.

### 1.6 Commit

- [ ] **1.6.1** Commit: `feat(agent): LiteLLM router foundation w/ provider quirks + VCR tests (Closes #M3-1)`.

---

## Task 2: Mock provider for deterministic tests

`Mock` is the default in CI and dev. Returns canned responses by input fingerprint; raises on unknown to keep test surfaces honest.

### 2.1 Implementation

- [ ] **2.1.1** Create `packages/agent/src/suitest_agent/providers/mock.py`:
  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from decimal import Decimal
  from typing import AsyncIterator
  import hashlib, json, time

  from suitest_agent.providers.litellm_router import CompletionResult


  class MockProviderUnknownInputError(RuntimeError):
      def __init__(self, fingerprint: str, hint: str):
          super().__init__(f"No canned response for fingerprint {fingerprint}. Hint: {hint}")
          self.fingerprint = fingerprint


  @dataclass
  class CannedResponse:
      content: str = ""
      tool_calls: list[dict] | None = None
      tokens_in: int = 50
      tokens_out: int = 30
      cost_usd: Decimal = Decimal("0.0001")


  _CANNED: dict[str, CannedResponse] = {}


  def register(fingerprint: str, resp: CannedResponse) -> None:
      _CANNED[fingerprint] = resp


  def clear() -> None:
      _CANNED.clear()


  def fingerprint(messages: list[dict], tools: list[dict] | None) -> str:
      h = hashlib.sha256()
      h.update(json.dumps(messages, sort_keys=True, ensure_ascii=False).encode())
      if tools:
          h.update(json.dumps(tools, sort_keys=True).encode())
      return h.hexdigest()[:16]


  class MockRouter:
      def __init__(self, model: str = "mock-v1"):
          self.cfg = type("C", (), {"provider": "mock", "model": model})

      async def complete(self, *, messages, temperature=0.2, max_tokens=4096,
                         tools=None, seed=None) -> CompletionResult:
          fp = fingerprint(messages, tools)
          canned = _CANNED.get(fp)
          if canned is None:
              raise MockProviderUnknownInputError(fp, hint=str(messages[-1])[:120])
          return CompletionResult(
              content=canned.content,
              tool_calls=canned.tool_calls or [],
              tokens_in=canned.tokens_in, tokens_out=canned.tokens_out,
              cost_usd=canned.cost_usd, model="mock", provider="mock",
              duration_ms=1, raw_response=None,
          )

      async def stream(self, *, messages, temperature=0.2, max_tokens=4096,
                       tools=None, seed=None) -> AsyncIterator[dict]:
          result = await self.complete(messages=messages, temperature=temperature,
                                       max_tokens=max_tokens, tools=tools, seed=seed)
          # Chunk content into 10-char deltas to exercise stream pipelines.
          for i in range(0, len(result.content), 10):
              yield {"type": "content", "content_delta": result.content[i:i + 10]}
          for tc in result.tool_calls:
              yield {"type": "tool_call", "tool_call_id": tc["id"],
                     "tool_name": tc["name"], "arguments_delta": tc["arguments"]}
          yield {"type": "finish", "reason": "stop"}

      async def health_check(self) -> tuple[bool, int, str | None]:
          return True, 1, None
  ```

### 2.2 Test helpers

- [ ] **2.2.1** Create `packages/agent/tests/providers/_mock_helpers.py` exporting `register_canned(messages, tools, content, tool_calls)` that auto-derives the fingerprint. Used by every graph test in later tasks.

### 2.3 Tests

- [ ] **2.3.1** `packages/agent/tests/providers/test_mock.py`:
  - `test_mock_returns_canned_for_known_fingerprint` — register a response, assert `complete()` returns it.
  - `test_mock_raises_for_unknown` — un-registered fingerprint raises `MockProviderUnknownInputError`.
  - `test_mock_stream_yields_content_chunks` — content split into ≥1 delta chunks.
  - `test_mock_stream_emits_tool_call_then_finish` — register w/ tool_calls, assert sequence.
  - `test_fingerprint_stable` — same inputs → same fingerprint; order of dict keys irrelevant.

### 2.4 CI wiring

- [ ] **2.4.1** Update CI workflow (`.github/workflows/ci.yml`) — set `SUITEST_LLM_PROVIDER=mock` in agent test job, so any LLM call w/o registered canned fingerprint fails loudly.

### 2.5 Commit

- [ ] **2.5.1** Commit: `feat(agent): mock LLM provider w/ fingerprint-based canned responses (Closes #M3-1.2)`.

---

## Task 3: LLM config CRUD endpoints + encrypted key storage

The control-plane that allows users to upgrade ZERO → CLOUD/LOCAL. Path: `/workspaces/:id/llm-config`. Always accessible (otherwise users could not escape ZERO).

### 3.1 Pydantic schemas

- [ ] **3.1.1** Create `packages/shared/suitest_shared/schemas/llm_config.py`:
  ```python
  from __future__ import annotations
  from datetime import datetime
  from typing import Literal, Any
  from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

  SUPPORTED_PROVIDERS = {
      "none", "mock",
      "anthropic", "openai", "gemini", "groq", "openrouter",
      "azure", "bedrock", "vertex", "deepseek",
      "ollama", "llamacpp", "vllm", "lmstudio",
  }

  class LLMConfigPublic(BaseModel):
      model_config = ConfigDict(from_attributes=True, populate_by_name=True)
      id: str
      workspace_id: str
      provider: str
      model: str
      api_key_hint: str | None = None     # "sk-ant-…abcd"
      config: dict[str, Any] = Field(default_factory=dict, alias="config_json")
      is_active: bool
      last_validated_at: datetime | None = None
      created_at: datetime
      updated_at: datetime

  class LLMConfigWrite(BaseModel):
      provider: str
      model: str = Field(..., min_length=1)
      api_key: SecretStr | None = None
      config: dict[str, Any] = Field(default_factory=dict)

      @field_validator("provider")
      @classmethod
      def _validate_provider(cls, v: str) -> str:
          if v not in SUPPORTED_PROVIDERS:
              raise ValueError(f"Unsupported provider '{v}'. Supported: {sorted(SUPPORTED_PROVIDERS)}")
          return v

  class LLMConfigTestResult(BaseModel):
      ok: bool
      latency_ms: int
      first_token_ms: int | None = None
      model_echo: str | None = None
      error: dict[str, str] | None = None
  ```

### 3.2 Repository

- [ ] **3.2.1** Create `packages/db/suitest_db/repositories/llm_config_repo.py`:
  - `get_active_llm_config(session, workspace_id)` → row or None.
  - `upsert_llm_config(session, workspace_id, provider, model, api_key_encrypted, config_json, last_validated_at)` → returns row. Sets `is_active=True` on the upserted row and `False` on prior active rows (workspace-scoped).
  - `delete_active(session, workspace_id)` → marks `is_active=False`; preserves history rows.
  - `list_history(session, workspace_id, limit=20)`.

### 3.3 Service

- [ ] **3.3.1** Create `apps/api/src/suitest_api/services/llm_config_service.py`:
  ```python
  from __future__ import annotations
  from datetime import datetime, timezone
  from sqlalchemy.ext.asyncio import AsyncSession

  from suitest_core.crypto import encrypt
  from suitest_db.repositories.llm_config_repo import (
      get_active_llm_config, upsert_llm_config, delete_active,
  )
  from suitest_db.audit import write_audit
  from suitest_db.repositories.workspace_capability_repo import recompute_capability
  from suitest_api.notifications.ws import broadcast_capability_changed
  from suitest_shared.schemas.llm_config import (
      LLMConfigPublic, LLMConfigWrite, LLMConfigTestResult,
  )
  from suitest_agent.providers.litellm_router import LiteLLMRouter
  from suitest_agent.providers.settings import LiteLLMProviderConfig


  def _hint(api_key: str | None) -> str | None:
      if not api_key:
          return None
      if len(api_key) <= 8:
          return "****"
      return api_key[:6] + "…" + api_key[-4:]


  async def get(session: AsyncSession, workspace_id: str) -> LLMConfigPublic | None:
      row = await get_active_llm_config(session, workspace_id)
      if not row:
          return None
      # api_key never decrypted here; only hint returned. Hint computed from the stored
      # ciphertext metadata (we persist hint at write time alongside api_key_encrypted
      # via config_json["api_key_hint"]) — see upsert below.
      hint = (row.config_json or {}).get("api_key_hint")
      return LLMConfigPublic(
          id=row.id, workspace_id=row.workspace_id, provider=row.provider,
          model=row.model, api_key_hint=hint, config=row.config_json or {},
          is_active=row.is_active, last_validated_at=row.last_validated_at,
          created_at=row.created_at, updated_at=row.updated_at,
      )


  async def put(session: AsyncSession, *, workspace_id: str, actor_user_id: str,
                body: LLMConfigWrite) -> LLMConfigPublic:
      raw_key = body.api_key.get_secret_value() if body.api_key else None
      enc = encrypt(raw_key.encode()) if raw_key else None
      config = dict(body.config)
      if raw_key:
          config["api_key_hint"] = _hint(raw_key)
      row = await upsert_llm_config(
          session, workspace_id=workspace_id, provider=body.provider,
          model=body.model, api_key_encrypted=enc, config_json=config,
          last_validated_at=None,
      )
      await write_audit(session, workspace_id=workspace_id, actor_user_id=actor_user_id,
                        actor_type="user", action="llm_config.update",
                        resource_type="llm_config", resource_id=row.id,
                        before=None, after={"provider": body.provider, "model": body.model})
      await recompute_capability(session, workspace_id)
      await session.commit()
      await broadcast_capability_changed(workspace_id)
      return await get(session, workspace_id)  # type: ignore[return-value]


  async def delete(session: AsyncSession, *, workspace_id: str, actor_user_id: str) -> None:
      await delete_active(session, workspace_id)
      await write_audit(session, workspace_id=workspace_id, actor_user_id=actor_user_id,
                        actor_type="user", action="llm_config.delete",
                        resource_type="llm_config", resource_id=workspace_id,
                        before=None, after={"provider": "none"})
      await recompute_capability(session, workspace_id)
      await session.commit()
      await broadcast_capability_changed(workspace_id)


  async def test_connection(session: AsyncSession, *, workspace_id: str,
                            body: LLMConfigWrite) -> LLMConfigTestResult:
      cfg = LiteLLMProviderConfig(
          provider=body.provider, model=body.model,
          api_key=body.api_key, base_url=body.config.get("base_url"),
          timeout_ms=body.config.get("timeout_ms", 30_000),
          aws_region=body.config.get("aws_region"),
          gcp_project=body.config.get("gcp_project"),
          gcp_location=body.config.get("gcp_location"),
          gcp_credentials_path=body.config.get("gcp_credentials_path"),
      )
      router = LiteLLMRouter(cfg)
      ok, latency, err = await router.health_check()
      if not ok:
          return LLMConfigTestResult(ok=False, latency_ms=latency,
                                     error={"code": "PROVIDER_AUTH", "message": err or "unknown"})
      return LLMConfigTestResult(ok=True, latency_ms=latency, model_echo=body.model)
  ```

### 3.4 Router

- [ ] **3.4.1** Create `apps/api/src/suitest_api/routers/llm_config.py`:
  ```python
  from fastapi import APIRouter, Depends, HTTPException, status
  from sqlalchemy.ext.asyncio import AsyncSession

  from suitest_api.deps.auth import current_admin_user
  from suitest_api.deps.db import get_session
  from suitest_api.services import llm_config_service as svc
  from suitest_shared.schemas.llm_config import (
      LLMConfigPublic, LLMConfigWrite, LLMConfigTestResult,
  )

  router = APIRouter(prefix="/workspaces/{workspace_id}/llm-config", tags=["llm-config"])


  @router.get("", response_model=LLMConfigPublic | None)
  async def get_(workspace_id: str, db: AsyncSession = Depends(get_session),
                 _user=Depends(current_admin_user)):
      return await svc.get(db, workspace_id)


  @router.put("", response_model=LLMConfigPublic)
  async def put_(workspace_id: str, body: LLMConfigWrite,
                 db: AsyncSession = Depends(get_session),
                 user=Depends(current_admin_user)):
      return await svc.put(db, workspace_id=workspace_id, actor_user_id=str(user.id), body=body)


  @router.post("/test", response_model=LLMConfigTestResult)
  async def test_(workspace_id: str, body: LLMConfigWrite,
                  db: AsyncSession = Depends(get_session),
                  _user=Depends(current_admin_user)):
      return await svc.test_connection(db, workspace_id=workspace_id, body=body)


  @router.delete("", status_code=status.HTTP_204_NO_CONTENT)
  async def delete_(workspace_id: str, db: AsyncSession = Depends(get_session),
                    user=Depends(current_admin_user)):
      await svc.delete(db, workspace_id=workspace_id, actor_user_id=str(user.id))
  ```
- [ ] **3.4.2** Register router in `apps/api/src/suitest_api/main.py` after existing routers, before `app.include_router(websocket_router)`.

### 3.5 Tests

- [ ] **3.5.1** `apps/api/tests/test_llm_config.py` (pytest-asyncio, real DB via test fixture, **respx-mocked** LiteLLM calls):
  - `test_get_returns_none_when_unset` — workspace fresh, GET returns 200 + `null`.
  - `test_put_stores_encrypted_key_and_flips_capability` — PUT with `provider=anthropic, model=claude-sonnet-4-5, api_key=sk-ant-x`; reload `workspace_capabilities` row → `tier == CLOUD`. Stored `api_key_encrypted` decrypts back to `sk-ant-x`.
  - `test_get_returns_hint_not_key` — after PUT, GET returns `api_key_hint="sk-ant…ant-x"` (or similar), never plaintext.
  - `test_test_connection_ok` — respx stub `https://api.anthropic.com/v1/messages` → 200 minimal response; POST `/test` → `{ok: true, latency_ms > 0}`.
  - `test_test_connection_auth_fail` — respx returns 401; POST `/test` → `{ok: false, error: {code: PROVIDER_AUTH}}`.
  - `test_put_unsupported_provider_400` — body `{provider: "made-up"}` → 422 with validator error.
  - `test_delete_clears_active_and_downgrades_to_zero` — DELETE after a CLOUD put → `workspace_capabilities.tier == ZERO`.
  - `test_capability_changed_event_broadcast` — assert WS pub/sub mock received `capability.changed` with new tier value.
  - `test_zero_tier_can_still_save_provider_none` — `provider=none` body accepted; tier stays ZERO.

### 3.6 Commit

- [ ] **3.6.1** Commit: `feat(api): LLM config CRUD w/ AES-GCM key + tier recompute (Closes #M3-2)`.

---

## Task 4: Tier + autonomy DI guards

FastAPI dependencies enforced at the boundary. Single source of truth for tier+autonomy gating; eliminates code-path drift.

### 4.1 Context object

- [ ] **4.1.1** Create `apps/api/src/suitest_api/deps/agent_ctx.py`:
  ```python
  from __future__ import annotations
  from contextvars import ContextVar
  from dataclasses import dataclass
  from fastapi import Depends, HTTPException
  from sqlalchemy.ext.asyncio import AsyncSession

  from suitest_shared.domain.enums import Tier, AutonomyLevel
  from suitest_db.repositories.workspace_capability_repo import get_capability
  from suitest_db.repositories.autonomy_repo import get_by_workspace as get_autonomy
  from suitest_api.deps.db import get_session
  from suitest_api.deps.auth import current_user

  @dataclass(frozen=True)
  class AgentContext:
      workspace_id: str
      user_id: str | None
      tier: Tier
      autonomy: AutonomyLevel
      autonomy_overrides: dict[str, bool]


  _CURRENT: ContextVar[AgentContext | None] = ContextVar("agent_ctx", default=None)


  async def build_ctx(workspace_id: str,
                      db: AsyncSession = Depends(get_session),
                      user=Depends(current_user)) -> AgentContext:
      cap = await get_capability(db, workspace_id)
      if cap is None:
          raise HTTPException(404, "workspace_capability not initialized")
      auto = await get_autonomy(db, workspace_id)
      ctx = AgentContext(
          workspace_id=workspace_id, user_id=str(user.id) if user else None,
          tier=Tier(cap.tier), autonomy=AutonomyLevel(auto.level if auto else "manual"),
          autonomy_overrides=(auto.overrides_json if auto else {}) or {},
      )
      _CURRENT.set(ctx)
      return ctx


  def current_ctx() -> AgentContext:
      ctx = _CURRENT.get()
      if ctx is None:
          raise RuntimeError("AgentContext not set — wire Depends(build_ctx) on this route")
      return ctx
  ```

### 4.2 Guards

- [ ] **4.2.1** Create `apps/api/src/suitest_api/deps/tier.py`:
  ```python
  from __future__ import annotations
  from typing import Iterable
  from fastapi import Depends, HTTPException
  from suitest_api.deps.agent_ctx import AgentContext, build_ctx
  from suitest_shared.domain.enums import Tier, AutonomyLevel


  def require_tier(*allowed: Tier):
      allowed_set = set(allowed)
      async def dep(workspace_id: str, ctx: AgentContext = Depends(build_ctx)) -> AgentContext:
          if ctx.tier not in allowed_set:
              raise HTTPException(
                  status_code=503,
                  detail={"error": {
                      "code": "LLM_DISABLED",
                      "message": "This feature requires an LLM provider.",
                      "details": {"required_tier": [t.value for t in allowed_set],
                                  "current_tier": ctx.tier.value},
                      "docsUrl": "/docs/capability-tiers",
                  }},
              )
          return ctx
      return dep


  def require_autonomy(min_level: AutonomyLevel):
      async def dep(workspace_id: str, ctx: AgentContext = Depends(build_ctx)) -> AgentContext:
          if ctx.autonomy.value_int < min_level.value_int:
              raise HTTPException(
                  status_code=403,
                  detail={"error": {
                      "code": "AUTONOMY_LEVEL_INSUFFICIENT",
                      "message": f"Requires autonomy ≥ {min_level.value}.",
                      "details": {"required": min_level.value, "current": ctx.autonomy.value},
                      "docsUrl": "/docs/autonomy",
                  }},
              )
          return ctx
      return dep
  ```
- [ ] **4.2.2** Augment `packages/shared/suitest_shared/domain/enums.py` `AutonomyLevel` with helper `@property value_int`:
  ```python
  class AutonomyLevel(StrEnum):
      MANUAL = "manual"
      ASSIST = "assist"
      SEMI_AUTO = "semi_auto"
      AUTO = "auto"

      @property
      def value_int(self) -> int:
          return {"manual": 0, "assist": 1, "semi_auto": 2, "auto": 3}[self.value]
  ```

### 4.3 Tests

- [ ] **4.3.1** `apps/api/tests/test_deps_tier.py`:
  - `test_require_tier_503_when_zero_and_cloud_required` — boot test app with workspace tier=ZERO, hit a stub endpoint guarded by `require_tier(Tier.CLOUD, Tier.LOCAL)` → 503 + `code=LLM_DISABLED` + `current_tier=ZERO`.
  - `test_require_tier_passes_when_cloud` — same stub, workspace upgraded to CLOUD → 200.
  - `test_require_autonomy_403_when_manual_and_assist_required` — workspace CLOUD + autonomy=manual, hit endpoint guarded by `require_autonomy(ASSIST)` → 403 + `code=AUTONOMY_LEVEL_INSUFFICIENT`.
  - `test_require_autonomy_passes_when_assist` — workspace CLOUD + autonomy=assist → 200.
  - `test_ctx_cached_per_request` — assert `build_ctx` only called once even when multiple guards stacked (via instrumentation patch).
  - `test_ctx_unavailable_outside_request` — `current_ctx()` outside FastAPI request raises `RuntimeError`.

### 4.4 Commit

- [ ] **4.4.1** Commit: `feat(api): require_tier + require_autonomy DI guards w/ AgentContext (Closes #M3-3)`.

---

## Task 5: Prompt versioning system

Versioned prompts with sha256 pinning. Persists on first use; reused across sessions.

### 5.1 Prompt files

- [ ] **5.1.1** Create directory `packages/agent/src/suitest_agent/prompts/v1/` with these files (each a complete Markdown prompt, drawn from AI_AGENT.md):
  - `system-base.md` — content from AI_AGENT.md §6, verbatim.
  - `generate-from-prd.md` — content from AI_AGENT.md §8.1.
  - `generate-from-url-semantic.md` — directives for browser-use semantic exploration.
  - `generate-from-mcp-discovery.md` — directives for tool exploration loop.
  - `generate-from-openapi-enrich.md` — directives for additive edge cases.
  - `execute-run.md` — directives for `action → MCP tool call sequence` translation, including MCP discovery hints + JSON output schema.
  - `diagnose.md` — directives for structured `{rootCause, confidence, evidenceFiles, suggestedFix, category}` output.
  - `conversation.md` — directives for ask mode; no mutations w/o explicit confirm.
- [ ] **5.1.2** Each file starts with a `## Frontmatter` header block (HTML comment) declaring its expected output JSON schema for structured-output prompts:
  ```html
  <!--
  output_schema:
    type: object
    properties:
      rootCause: { type: string, maxLength: 400 }
      confidence: { type: number, minimum: 0, maximum: 1 }
      category: { type: string, enum: [REGRESSION, FLAKE, INFRA, SPEC_DRIFT, MANUAL_TRIAGE] }
      evidenceFiles:
        type: array
        items:
          type: object
          properties:
            path: { type: string }
            lineNumber: { type: integer }
      suggestedFix: { type: string, nullable: true }
    required: [rootCause, confidence, category, evidenceFiles]
  -->
  ```

### 5.2 Loader

- [ ] **5.2.1** Create `packages/agent/src/suitest_agent/prompts/loader.py`:
  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from pathlib import Path
  import hashlib

  from sqlalchemy.ext.asyncio import AsyncSession
  from suitest_db.repositories.prompt_version_repo import get_or_create as repo_get_or_create

  PROMPTS_ROOT = Path(__file__).parent

  @dataclass(frozen=True)
  class LoadedPrompt:
      name: str          # "v1/generate-from-prd"
      version: str       # "1.0.0"
      content: str
      sha256: str
      id: str | None = None    # populated after persist

  def load(name: str, version: str = "1.0.0") -> LoadedPrompt:
      ver_dir = PROMPTS_ROOT / name.split("/")[0]   # "v1"
      filename = name.split("/", 1)[1] + ".md"
      path = ver_dir / filename
      content = path.read_text(encoding="utf-8")
      h = hashlib.sha256(content.encode()).hexdigest()
      return LoadedPrompt(name=name, version=version, content=content, sha256=h)

  async def ensure_persisted(db: AsyncSession, p: LoadedPrompt) -> LoadedPrompt:
      row = await repo_get_or_create(db, name=p.name, version=p.version,
                                     content=p.content, sha256=p.sha256)
      return LoadedPrompt(name=p.name, version=p.version, content=p.content,
                          sha256=p.sha256, id=row.id)
  ```

### 5.3 Repository

- [ ] **5.3.1** Create `packages/db/suitest_db/repositories/prompt_version_repo.py`:
  - `get_or_create(session, *, name, version, content, sha256)` → idempotent: if `(name, version)` row exists with matching `hash`, return; if exists with **different** hash, raise `PromptVersionContentDrift` (signals an edit to a pinned version — coder must bump `version`).
  - `get_by_id(session, id)`.

### 5.4 Tests

- [ ] **5.4.1** `packages/agent/tests/prompts/test_loader.py`:
  - `test_load_returns_content_and_hash` — load `v1/generate-from-prd` → content non-empty, hash 64 chars.
  - `test_load_unknown_raises_filenotfound` — `load("v1/nope")` → `FileNotFoundError`.
- [ ] **5.4.2** `packages/db/tests/test_prompt_version_repo.py`:
  - `test_get_or_create_inserts_first_time` — empty table, call → row inserted; `id` returned; `hash` matches.
  - `test_get_or_create_idempotent_same_content` — call twice → same row id.
  - `test_get_or_create_raises_on_content_drift` — pre-insert row `(v1/x, 1.0.0, "hello", sha256_a)`; call with same name+version but different content → `PromptVersionContentDrift`.

### 5.5 Commit

- [ ] **5.5.1** Commit: `feat(agent): prompt loader + versioning w/ sha256 pinning (Closes #M3-5)`.

---

## Task 6: Tool registry (LLM-callable tools)

The set of tools the LLM can call. Each tool: Pydantic schema → OpenAI-compatible tool JSON. Filtering per mode.

### 6.1 Base types

- [ ] **6.1.1** Create `packages/agent/src/suitest_agent/tools/registry.py`:
  ```python
  from __future__ import annotations
  from dataclasses import dataclass, field
  from typing import Awaitable, Callable, Protocol
  from pydantic import BaseModel

  from suitest_shared.domain.enums import Tier, AutonomyLevel


  class ToolHandler(Protocol):
      async def __call__(self, args: BaseModel, *, ctx) -> dict: ...


  @dataclass(frozen=True)
  class ToolSpec:
      name: str
      description: str
      schema: type[BaseModel]
      handler: ToolHandler
      min_tier: Tier = Tier.ZERO
      min_autonomy: AutonomyLevel = AutonomyLevel.ASSIST
      mutates: bool = False

      def to_openai_tool(self) -> dict:
          schema = self.schema.model_json_schema()
          schema.pop("title", None)
          return {
              "type": "function",
              "function": {
                  "name": self.name,
                  "description": self.description,
                  "parameters": schema,
              },
          }


  class ToolRegistry:
      def __init__(self) -> None:
          self._tools: dict[str, ToolSpec] = {}

      def register(self, spec: ToolSpec) -> None:
          if spec.name in self._tools:
              raise ValueError(f"Tool {spec.name} already registered")
          self._tools[spec.name] = spec

      def filter_for_mode(self, names: list[str]) -> list[ToolSpec]:
          missing = [n for n in names if n not in self._tools]
          if missing:
              raise KeyError(f"Unknown tools: {missing}")
          return [self._tools[n] for n in names]

      def to_litellm_tools(self, names: list[str]) -> list[dict]:
          return [t.to_openai_tool() for t in self.filter_for_mode(names)]

      async def dispatch(self, name: str, raw_args: dict, *, ctx) -> dict:
          tool = self._tools[name]
          parsed = tool.schema(**raw_args)
          if ctx.autonomy.value_int < tool.min_autonomy.value_int and tool.mutates:
              raise PermissionError(f"Autonomy {ctx.autonomy} < {tool.min_autonomy} for {name}")
          return await tool.handler(parsed, ctx=ctx)


  REGISTRY = ToolRegistry()
  ```

### 6.2 Individual tool modules

For each tool below, create a file in `packages/agent/src/suitest_agent/tools/` defining the `args` Pydantic class + an async `handler` + a `register()` call at import time.

- [ ] **6.2.1** `tools/docs.py` → `docs.read`, `docs.list_endpoints`.
- [ ] **6.2.2** `tools/code.py` → `code.read` (reads file from GitHub via integration token, fallback local clone). For ZERO compatibility the tool itself is min_tier=ZERO; only USED by DIAGNOSIS graph in CLOUD/LOCAL.
- [ ] **6.2.3** `tools/mcp.py` → `mcp.invoke`, `mcp.invoke_typed`, `mcp.discover_tools`. Wraps `packages/mcp/client` from M1c.
- [ ] **6.2.4** `tools/db.py` → `db.query_cases`, `db.query_runs`, `db.query_defects`. Read-only via repository layer. Workspace-scoped via ctx.
- [ ] **6.2.5** `tools/cases.py` → `cases.create` (mutates=True, min_tier=Tier.CLOUD|Tier.LOCAL). Calls `test_case_service.create_draft`.
- [ ] **6.2.6** `tools/defect.py` → `defect.create` (mutates=True).
- [ ] **6.2.7** `tools/tracker.py` → `tracker.create_issue` (mutates=True). Calls Jira/Linear/GitHub adapter (M1d).
- [ ] **6.2.8** `tools/search.py` → `search.suite` (FTS + optional pgvector). Workspace-scoped.
- [ ] **6.2.9** `tools/target.py` → `target.classify` (deterministic; reuse `packages/agent/generators/classifier.py` from M2).
- [ ] **6.2.10** `tools/export.py` → `case.export` (deterministic; reuse M2 exporter).

### 6.3 Subsets per mode

- [ ] **6.3.1** `packages/agent/src/suitest_agent/tools/subsets.py`:
  ```python
  GENERATION_TOOLS = ["docs.read", "docs.list_endpoints", "search.suite",
                      "target.classify", "cases.create", "case.export",
                      "mcp.discover_tools"]
  EXECUTION_TOOLS = ["mcp.invoke", "mcp.invoke_typed", "mcp.discover_tools",
                     "db.query_cases"]
  DIAGNOSIS_TOOLS = ["code.read", "db.query_runs", "db.query_defects",
                     "defect.create", "tracker.create_issue"]
  CONVERSATION_TOOLS = ["docs.read", "db.query_cases", "db.query_runs",
                        "db.query_defects", "search.suite"]
  ```

### 6.4 Tests

- [ ] **6.4.1** `packages/agent/tests/tools/test_registry.py`:
  - `test_to_openai_tool_schema_valid` — round-trip schema is valid against OpenAI tool-format JSON Schema meta-schema.
  - `test_filter_for_mode_raises_on_unknown`.
  - `test_dispatch_validates_args` — pass invalid args → `pydantic.ValidationError`.
  - `test_mutates_tool_blocked_below_autonomy` — dispatching `cases.create` with ctx autonomy=manual → `PermissionError`.
  - `test_db_query_cases_workspace_scoped` — seed 2 workspaces with cases each; call with ctx.workspace_id=A → only A's cases returned.
  - `test_target_classify_deterministic_matches_m2` — invoke `target.classify` with sample inputs → same output as `packages/agent/generators/classifier.classify`.

### 6.5 Commit

- [ ] **6.5.1** Commit: `feat(agent): tool registry + 13 tools w/ Pydantic schemas (Closes #M3-6)`.

---

## Task 7: LangGraph base infra

Shared LangGraph plumbing: state schema, Postgres checkpointer, cancel event plumbing, streaming bridge to FastAPI SSE/WS.

### 7.1 Checkpointer

- [ ] **7.1.1** Create `packages/agent/src/suitest_agent/graphs/checkpointer.py`:
  ```python
  from __future__ import annotations
  import os
  from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

  _saver: AsyncPostgresSaver | None = None

  async def get_saver() -> AsyncPostgresSaver:
      global _saver
      if _saver is None:
          url = os.environ["SUITEST_DATABASE_URL"]
          _saver = AsyncPostgresSaver.from_conn_string(url)
          await _saver.setup()   # idempotent — creates checkpoint tables if missing
      return _saver
  ```

### 7.2 Cancel plumbing

- [ ] **7.2.1** Create `packages/agent/src/suitest_agent/graphs/cancel.py`:
  ```python
  from __future__ import annotations
  import asyncio
  from contextvars import ContextVar

  cancel_event: ContextVar[asyncio.Event | None] = ContextVar("agent_cancel_event", default=None)

  class AgentCancelled(RuntimeError):
      pass

  def raise_if_cancelled() -> None:
      ev = cancel_event.get()
      if ev is not None and ev.is_set():
          raise AgentCancelled("agent.session.cancel requested")
  ```

### 7.3 State base

- [ ] **7.3.1** Create `packages/agent/src/suitest_agent/graphs/state.py`:
  ```python
  from __future__ import annotations
  from typing import Annotated
  from pydantic import BaseModel
  from suitest_shared.domain.enums import Tier, AutonomyLevel

  class GraphCtx(BaseModel):
      session_id: str
      workspace_id: str
      user_id: str | None
      tier: Tier
      autonomy: AutonomyLevel
      autonomy_overrides: dict[str, bool] = {}
      prompt_version_id: str
      model: str
      provider: str
      seed: int | None = None
      temperature: float = 0.2

  class BaseGraphState(BaseModel):
      ctx: GraphCtx
      messages: list[dict] = []
      tool_calls: list[dict] = []
  ```

### 7.4 Streaming bridge

- [ ] **7.4.1** Create `packages/agent/src/suitest_agent/graphs/streaming.py`:
  ```python
  from __future__ import annotations
  from typing import AsyncIterator, Any
  import json
  import asyncio

  async def sse_format(events: AsyncIterator[dict]) -> AsyncIterator[bytes]:
      async for ev in events:
          payload = json.dumps(ev["data"], ensure_ascii=False)
          yield f"event: {ev['type']}\ndata: {payload}\n\n".encode()
      # final close marker
      yield b"event: done\ndata: {}\n\n"

  async def heartbeat(interval_s: float = 15.0) -> AsyncIterator[dict]:
      while True:
          await asyncio.sleep(interval_s)
          yield {"type": "ping", "data": {}}
  ```
- [ ] **7.4.2** Create `packages/agent/src/suitest_agent/graphs/ws_bridge.py` — Pub/Sub to Redis channel `agent-session:<session_id>` for fan-out to FastAPI WebSocket clients (tool/approval events).

### 7.5 Tests

- [ ] **7.5.1** `packages/agent/tests/graphs/test_base.py`:
  - `test_trivial_graph_runs_and_persists_checkpoint` — define a 2-node graph (start → done), compile with checkpointer, run, assert checkpoint row exists.
  - `test_resume_from_checkpoint` — invoke same `thread_id` again → returns immediately.
  - `test_cancel_event_aborts` — start a graph whose first node sleeps 1s + checks cancellation; set event after 50ms → `AgentCancelled` raised; checkpoint records `cancelled` status.
  - `test_sse_format_yields_event_data_blocks` — feed two events, assert frames have `event: foo\ndata: {...}\n\n`.

### 7.6 Commit

- [ ] **7.6.1** Commit: `feat(agent): LangGraph base infra (checkpointer, cancel, streaming) (Closes #M3-4)`.

---

## Task 8: GENERATION mode — PRD source

LangGraph that ingests a PRD blob, decomposes to stories, drafts cases. Streams cases via SSE.

### 8.1 Graph definition

- [ ] **8.1.1** Create `packages/agent/src/suitest_agent/graphs/generate_from_prd.py`:
  ```python
  from __future__ import annotations
  from typing import Any
  from pydantic import BaseModel
  from langgraph.graph import StateGraph, END, Send

  from suitest_agent.graphs.state import BaseGraphState
  from suitest_agent.graphs.cancel import raise_if_cancelled
  from suitest_agent.providers.litellm_router import LiteLLMRouter
  from suitest_agent.tools.registry import REGISTRY
  from suitest_agent.tools.subsets import GENERATION_TOOLS
  from suitest_agent.prompts.loader import load, ensure_persisted

  class Story(BaseModel):
      title: str
      actor: str
      action: str
      expected: str
      priority: str = "P2"

  class DraftCase(BaseModel):
      name: str
      description: str
      priority: str
      target_kind: str
      mcp_provider: str
      steps: list[dict]

  class PRDState(BaseGraphState):
      input_text: str
      target_suite_id: str
      stories: list[Story] = []
      similar_cases: list[dict] = []
      draft_cases: list[DraftCase] = []
      emitted_ids: list[str] = []

  async def chunk_input_node(state: PRDState) -> PRDState:
      # simple: split by markdown headers; deferred semantic chunk to M4
      ...

  async def retrieve_rag_node(state: PRDState) -> PRDState:
      ...

  async def search_existing_suite_node(state: PRDState) -> PRDState:
      ...

  async def extract_stories_node(router: LiteLLMRouter, state: PRDState) -> PRDState:
      raise_if_cancelled()
      ...

  async def for_each_story_node(state: PRDState):
      return [Send("draft_one", {"story": s, "ctx": state.ctx}) for s in state.stories]

  async def draft_one_node(router: LiteLLMRouter, payload: dict) -> dict:
      raise_if_cancelled()
      ...

  async def persist_drafts_node(state: PRDState) -> PRDState:
      ...

  def build(router: LiteLLMRouter):
      g = StateGraph(PRDState)
      g.add_node("chunk_input", chunk_input_node)
      g.add_node("retrieve_rag", retrieve_rag_node)
      g.add_node("search_existing", search_existing_suite_node)
      g.add_node("extract_stories", lambda s: extract_stories_node(router, s))
      g.add_node("draft_one", lambda p: draft_one_node(router, p))
      g.add_node("persist_drafts", persist_drafts_node)
      g.set_entry_point("chunk_input")
      g.add_edge("chunk_input", "retrieve_rag")
      g.add_edge("retrieve_rag", "search_existing")
      g.add_edge("search_existing", "extract_stories")
      g.add_conditional_edges("extract_stories", for_each_story_node, ["draft_one"])
      g.add_edge("draft_one", "persist_drafts")
      g.add_edge("persist_drafts", END)
      return g
  ```
- [ ] **8.1.2** Fill in node bodies per AI_AGENT.md §8.1. Each LLM-calling node uses `await router.complete(messages=[...], temperature=ctx.temperature, max_tokens=..., tools=REGISTRY.to_litellm_tools(GENERATION_TOOLS), seed=ctx.seed)`.
- [ ] **8.1.3** `draft_one_node` returns a `DraftCase` (Pydantic parsed from LLM JSON output); `persist_drafts_node` writes via `cases.create` tool dispatch.

### 8.2 API endpoint

- [ ] **8.2.1** Extend `apps/api/src/suitest_api/routers/agent.py` (or create if absent):
  ```python
  from fastapi import APIRouter, Depends
  from fastapi.responses import StreamingResponse
  from suitest_api.deps.tier import require_tier, require_autonomy
  from suitest_shared.domain.enums import Tier, AutonomyLevel
  from suitest_shared.schemas.agent_generate import AgentGenerateRequest

  router = APIRouter(prefix="/agent", tags=["agent"])

  @router.post("/generate/cases")
  async def generate_cases(
      body: AgentGenerateRequest,
      ctx=Depends(require_tier(Tier.CLOUD, Tier.LOCAL)),
      __=Depends(require_autonomy(AutonomyLevel.ASSIST)),
  ):
      from suitest_api.services.agent_generation_service import run_generation
      return StreamingResponse(
          run_generation(body, ctx=ctx),
          media_type="text/event-stream",
          headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
      )
  ```
- [ ] **8.2.2** `suitest_shared/schemas/agent_generate.py`:
  ```python
  from __future__ import annotations
  from typing import Literal
  from pydantic import BaseModel, Field

  Source = Literal["PRD", "URL_SEMANTIC", "MCP_DISCOVERY", "OPENAPI_ENRICH"]

  class AgentGenerateInput(BaseModel):
      type: Literal["text", "url", "documentId", "mcp_provider_id"]
      value: str

  class AgentGenerateOptions(BaseModel):
      maxCases: int = Field(10, ge=1, le=50)
      priorityHint: str | None = None
      tagPrefix: str | None = None

  class AgentGenerateRequest(BaseModel):
      source: Source
      input: AgentGenerateInput
      targetSuiteId: str
      targetKind: str | None = None
      mcpProviderId: str | None = None
      strategy: Literal["ai_only", "ai_enrich"] = "ai_only"
      options: AgentGenerateOptions = AgentGenerateOptions()
      modelHint: str | None = None
  ```

### 8.3 Service

- [ ] **8.3.1** `apps/api/src/suitest_api/services/agent_generation_service.py`:
  ```python
  from __future__ import annotations
  from typing import AsyncIterator
  import asyncio
  import json
  from sqlalchemy.ext.asyncio import AsyncSession

  from suitest_agent.providers.factory import build_router_for_workspace
  from suitest_agent.graphs.generate_from_prd import build as build_prd_graph, PRDState
  from suitest_agent.graphs.state import GraphCtx
  from suitest_agent.graphs.checkpointer import get_saver
  from suitest_agent.graphs.cancel import cancel_event, AgentCancelled
  from suitest_agent.prompts.loader import load, ensure_persisted
  from suitest_db.repositories.agent_session_repo import create_session, mark_completed
  from suitest_db.repositories.generator_run_repo import create as create_gen_run

  async def run_generation(body, *, ctx) -> AsyncIterator[bytes]:
      async with new_session_scope() as db:
          router = await build_router_for_workspace(ctx.workspace_id, db=db)
          prompt = await ensure_persisted(db, load("v1/generate-from-prd"))
          session = await create_session(
              db, workspace_id=ctx.workspace_id, user_id=ctx.user_id, kind="GENERATION",
              model_id=body.modelHint or router.cfg.model, provider=router.cfg.provider,
              prompt_version_id=prompt.id, seed=None, temperature=0.2,
              metadata={"source": body.source, "targetSuiteId": body.targetSuiteId,
                       "strategy": body.strategy},
          )
          await db.commit()
          ev = asyncio.Event()
          tok = cancel_event.set(ev)
          try:
              graph = build_prd_graph(router).compile(checkpointer=await get_saver())
              initial = PRDState(
                  ctx=GraphCtx(session_id=session.id, workspace_id=ctx.workspace_id,
                               user_id=ctx.user_id, tier=ctx.tier, autonomy=ctx.autonomy,
                               autonomy_overrides=ctx.autonomy_overrides,
                               prompt_version_id=prompt.id, model=router.cfg.model,
                               provider=router.cfg.provider, temperature=0.2),
                  input_text=body.input.value, target_suite_id=body.targetSuiteId,
              )
              yield _sse("agent.session.started", {"sessionId": session.id,
                                                   "mode": "GENERATION",
                                                   "model": router.cfg.model,
                                                   "promptVersionId": prompt.id})
              async for event in graph.astream_events(initial, version="v2",
                                                      config={"configurable": {
                                                          "thread_id": session.id}}):
                  if event["event"] == "on_chain_end" and event["name"] == "draft_one":
                      draft = event["data"]["output"]
                      yield _sse("case", {"id": draft.public_id, "name": draft.name,
                                          "steps": draft.steps})
              await mark_completed(db, session.id, status="completed")
              await db.commit()
              yield _sse("complete", {"totalGenerated": ...,
                                       "sessionId": session.id,
                                       "tokensUsed": ...})
          except AgentCancelled:
              await mark_completed(db, session.id, status="cancelled")
              await db.commit()
              yield _sse("agent.session.cancelled", {"sessionId": session.id})
          finally:
              cancel_event.reset(tok)

  def _sse(event: str, data: dict) -> bytes:
      return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()
  ```

### 8.4 Tests

- [ ] **8.4.1** `packages/agent/tests/graphs/test_generate_from_prd.py`:
  - Use `MockRouter`. Register canned LLM responses for: (a) story extraction returning 3 stories JSON; (b) per-story draft response returning a `DraftCase` JSON. Wrap the graph + run; assert 3 draft cases produced.
  - Each case has `status="DRAFT"`, ≥2 steps, every step has `action`, `expected`, `target_kind`, `mcp_provider`.
  - `test_generation_run_persists_session_row_with_prompt_version`.
  - `test_generation_emits_sse_case_per_draft` — collect SSE bytes, decode → expect ≥3 `event: case` frames.
- [ ] **8.4.2** Optional VCR cassette `cassettes/anthropic/generate_prd_e2e.yaml` (admin-recorded) — assert real anthropic 3-5 cases generated.

### 8.5 Autonomy gate on result status

- [ ] **8.5.1** In `persist_drafts_node`, set case status based on `ctx.autonomy + priority` (autonomy matrix per AUTONOMY.md §3):
  - `assist` → all DRAFT
  - `semi_auto` → P2/P3 ACTIVE, P0/P1 DRAFT
  - `auto` → all ACTIVE (modulo `gen_finalize_p2p3` override flag)

### 8.6 Commit

- [ ] **8.6.1** Commit: `feat(agent): GENERATION graph from PRD w/ SSE streaming (Closes #M3-6)`.

---

## Task 9: GENERATION mode — URL semantic

LangGraph that drives `browser-use-mcp` agentically. Slow (10-30s/case) but semantically aware.

### 9.1 Graph

- [ ] **9.1.1** Create `packages/agent/src/suitest_agent/graphs/generate_from_url_semantic.py`:
  - Nodes: `launch_browser_mcp` → `snapshot_dom` → `identify_flows` (LLM) → for each flow `explore_run` (`mcp.invoke` browser-use semantic primitives) → `observe_outcome` → `draft_case_from_trace` (LLM) → `persist_drafts`.
  - Uses `mcp.invoke` tool against `browser-use-mcp` provider (bundled in M2).
  - Reads prompt `v1/generate-from-url-semantic.md`.
- [ ] **9.1.2** Identify-flows node hits LLM with the DOM snapshot + intent hint from `body.options`. Returns list of `{name, entry_url, completion_criterion}`.
- [ ] **9.1.3** Per-flow exploration limited to N agent steps (default 12) to bound cost.

### 9.2 Service wiring

- [ ] **9.2.1** In `agent_generation_service.py`, route `source == "URL_SEMANTIC"` to this graph.

### 9.3 Tests

- [ ] **9.3.1** `packages/agent/tests/graphs/test_generate_from_url_semantic.py`:
  - Stub `browser-use-mcp` via fake `McpInvoker` (M1c). Register canned LLM identify-flows + draft responses.
  - Assert ≥1 case produced with `target_kind="FE_WEB"`, `mcp_provider="browser-use-mcp"`.
  - `test_url_semantic_bounded_steps` — explore_run cycles ≤12.
  - `test_url_semantic_returns_503_in_zero_via_endpoint` — POST /agent/generate/cases body source=URL_SEMANTIC, workspace ZERO → 503.

### 9.4 Commit

- [ ] **9.4.1** Commit: `feat(agent): URL semantic generator via browser-use-mcp (Closes #M3-7)`.

---

## Task 10: GENERATION mode — MCP tool discovery

User registers custom MCP; LLM explores tools; generates exercising cases.

### 10.1 Graph

- [ ] **10.1.1** Create `packages/agent/src/suitest_agent/graphs/generate_from_mcp_discovery.py`:
  - Nodes: `connect_mcp` (uses `mcp.discover_tools`) → `summarize_tools` (LLM) → for each tool `plan_invocations` (LLM, returns list of `{valid, invalid}` arg sets) → `draft_case` (LLM) → `persist_drafts`.
  - Each generated case `target_kind="CUSTOM"`, `mcp_provider=<provider_id>`.

### 10.2 Service wiring

- [ ] **10.2.1** Route `source == "MCP_DISCOVERY"`, expects `input.value` is the `mcpProviderId` (registered via M2 endpoints).

### 10.3 Tests

- [ ] **10.3.1** `packages/agent/tests/graphs/test_generate_from_mcp_discovery.py`:
  - Use **filesystem-mcp** test fixture from M2 (bundled or stdio executable in `tests/fixtures/mcp/`).
  - Register canned LLM responses for tool summary + plan + draft.
  - Assert each discovered tool exercised by ≥1 case.
  - `test_mcp_discovery_target_kind_custom`.

### 10.4 Commit

- [ ] **10.4.1** Commit: `feat(agent): MCP tool discovery generator (Closes #M3-9)`.

---

## Task 11: GENERATION mode — OpenAPI enrich (hybrid)

Hybrid: deterministic from M2 + AI top-up. Always runs deterministic first; falls back to deterministic-only on LLM error.

### 11.1 Graph

- [ ] **11.1.1** Create `packages/agent/src/suitest_agent/graphs/generate_from_openapi_enrich.py`:
  - Nodes: `run_deterministic` (calls `packages/agent/generators/openapi.generate(spec)` from M2) → `for_each_operation` → `propose_edges` (LLM, takes operation + description + examples, returns list of additional cases) → `merge_dedupe` (Levenshtein over case name + step signature, threshold 0.85) → `persist_drafts`.
- [ ] **11.1.2** Failure handling: if any `propose_edges` raises or times out, skip that operation; continue. After all operations, if zero AI cases produced, emit warning event but still emit deterministic baseline.

### 11.2 Service wiring

- [ ] **11.2.1** Route `source == "OPENAPI_ENRICH"`. Mirror endpoint `POST /generators/openapi?enrich=true` per GENERATORS.md §5.4: routes to this graph when tier supports it; else returns deterministic only.

### 11.3 Tests

- [ ] **11.3.1** `packages/agent/tests/graphs/test_generate_from_openapi_enrich.py`:
  - Fixture: `tests/fixtures/openapi/petstore.json` (reuse from M2).
  - Register canned LLM proposal returning 2 extra edge cases per operation.
  - Assert final case count == deterministic_count + ai_count.
  - Dedupe: insert a duplicate canned AI proposal mirroring a deterministic case → merged count == deterministic_count + ai_count - 1.
  - `test_openapi_enrich_falls_back_to_deterministic_on_llm_error` — canned response raises; assert deterministic still emitted + warning event.

### 11.4 Commit

- [ ] **11.4.1** Commit: `feat(agent): OpenAPI enrich hybrid generator (Closes #M3-8)`.

---

## Task 12: EXECUTION mode — action→code translation

Runtime translation of `step.action` → MCP tool call. Wires into the M1c step executor.

### 12.1 Graph

- [ ] **12.1.1** Create `packages/agent/src/suitest_agent/graphs/execute_run.py`:
  - Single-shot per step (not run-level). Nodes: `classify_step` → if `code` present return ABORT (caller handles); else `discover_tools` (call `mcp.discover_tools` against `step.mcp_provider`) → `translate_action` (LLM, prompt `v1/execute-run.md`, output JSON `{tool, arguments, assertions}`) → `validate_against_schema` (Pydantic check against MCP tool schema) → `emit_translated_code`.
- [ ] **12.1.2** Caller persists `step.code` only if `autonomy_overrides.get("exec_persist_translated", True)` is true. Otherwise translation is ephemeral per-run (recorded on `run_steps.metadata_json.translated_code`).

### 12.2 Wiring into M1c step executor

- [ ] **12.2.1** Modify `apps/runner/src/suitest_runner/executors/step_executor.py` (currently emits `TODO(M3): agentic translate not yet implemented` per M1c plan §11):
  ```python
  if not test_step.code:
      if tier == Tier.ZERO:
          return _done(StepOutcome.SKIP, msg="NO_LLM_FOR_AGENTIC_STEP: step has no code")
      # M3 — LLM translation
      from suitest_agent.graphs.execute_run import translate_step
      try:
          translated = await translate_step(
              workspace_id=workspace_id, step=test_step, run_id=run_id,
              actor_user_id=actor_user_id,
          )
      except Exception as exc:
          return _done(StepOutcome.ERROR, msg=f"TRANSLATE_FAILED: {exc}")
      test_step = _patch_step(test_step, code=translated.code_json)
  ```
- [ ] **12.2.2** Add helper `_patch_step(step, *, code)` that returns a new MagicMock/dataclass with the JSON code set (does not mutate DB unless autonomy persistence flag set).

### 12.3 Autonomy gate on agentic step

- [ ] **12.3.1** Inside `translate_step`, if `ctx.autonomy == ASSIST`, emit `agent.step.confirm_required` over WS room `run:<run_id>` with translated payload; await approval message (5min timeout → mark SKIP with reason `AGENTIC_APPROVAL_TIMEOUT`).

### 12.4 Tests

- [ ] **12.4.1** `apps/runner/tests/test_step_executor_m3.py`:
  - `test_action_only_step_cloud_translates_and_executes_pass` — fake invoker; register canned LLM returning JSON for `mcp.api.request` against a stub MCP; assert `outcome == PASS`.
  - `test_action_only_step_zero_still_skips` — tier=ZERO unchanged from M1c.
  - `test_translate_failed_marks_error` — mock raises → outcome `ERROR` + `TRANSLATE_FAILED:` prefix.
  - `test_assist_emits_confirm_required_and_awaits_approval` — autonomy=assist; runner blocks until approval message; sends approval → executes.
  - `test_assist_timeout_marks_skip` — autonomy=assist; no approval after 5min (use freezegun) → SKIP.
- [ ] **12.4.2** `packages/agent/tests/graphs/test_execute_run.py`:
  - `test_translate_returns_validated_tool_call` — canned response with valid tool + args matching MCP schema → parsed `code_json` valid.
  - `test_translate_invalid_args_retries_with_feedback` — first canned response returns invalid args; LLM-self-correct loop kicks in (second canned response is valid). Max 2 retries.
  - `test_translate_records_messages_to_session`.

### 12.5 Commit

- [ ] **12.5.1** Commit: `feat(agent,runner): action→code translation at execution time (Closes #M3-10)`.

---

## Task 13: DIAGNOSIS mode — root cause analysis

Replaces M1d rule-based `MANUAL_TRIAGE` when tier != ZERO. Triggered automatically post-failure + via explicit endpoint.

### 13.1 Graph

- [ ] **13.1.1** Create `packages/agent/src/suitest_agent/graphs/diagnose.py`:
  - Nodes: `gather_context` (collects failed `RunStep` action+expected+actual+console_logs; last 3 commits touching files in stack trace via `code.read`; last 5 runs of same case via `db.query_runs`; case `step.code` if exists) → `classify_category` (LLM, returns one of `REGRESSION|FLAKE|INFRA|SPEC_DRIFT`) → `draft_diagnosis` (LLM, JSON output validated against the prompt frontmatter schema) → `attach_evidence` → `persist_to_defect`.
- [ ] **13.1.2** Output Pydantic model:
  ```python
  from pydantic import BaseModel, Field
  from typing import Literal

  class EvidenceRef(BaseModel):
      path: str
      lineNumber: int | None = None
      commitSha: str | None = None
      excerpt: str | None = None

  class DiagnosisOutput(BaseModel):
      rootCause: str = Field(..., max_length=400)
      confidence: float = Field(..., ge=0.0, le=1.0)
      category: Literal["REGRESSION", "FLAKE", "INFRA", "SPEC_DRIFT", "MANUAL_TRIAGE"]
      evidenceFiles: list[EvidenceRef]
      suggestedFix: str | None = None
      rerunRecommended: bool = False
  ```

### 13.2 Trigger points

- [ ] **13.2.1** **Auto on failure** — extend `apps/runner/src/suitest_runner/jobs/run_test_case.py` (M1c) to enqueue a `diagnose_run_step` job upon `RunStep.outcome == FAIL` when tier != ZERO and `autonomy >= ASSIST`. Use ARQ delayed enqueue (5s after run completion to avoid racing log persistence).
- [ ] **13.2.2** **Explicit** — endpoint `POST /agent/diagnose/runs/:run_id` with `require_tier(Tier.CLOUD, Tier.LOCAL)`.

### 13.3 Persistence

- [ ] **13.3.1** Map `DiagnosisOutput → defects` columns:
  - `defects.agent_diagnosis = output.rootCause + bullets-from-evidenceFiles`
  - `defects.agent_confidence = output.confidence`
  - `defects.agent_diagnosis_kind = output.category` (use enum already defined — extend `DiagnosisKind` to include `REGRESSION, FLAKE, INFRA, SPEC_DRIFT, MANUAL_TRIAGE`).
- [ ] **13.3.2** Replace M1d MANUAL_TRIAGE filer for the path where tier != ZERO: M1d still owns ZERO; M3 owns LOCAL/CLOUD.

### 13.4 Autonomy gate

- [ ] **13.4.1** Diagnosis output behavior per AUTONOMY.md:
  - `assist`: diagnose runs; defect stays `OPEN` and `agent_diagnosis_kind` set; **awaits human review** before any tracker.create_issue mutation.
  - `semi_auto`: auto-categorize; FLAKE auto-reruns max 2; REGRESSION blocks deploy; P0/P1 defects stay `OPEN` until human review.
  - `auto`: full automation including `tracker.create_issue` invocation.

### 13.5 Tests

- [ ] **13.5.1** `packages/agent/tests/graphs/test_diagnose.py`:
  - Fixture: a `Run` + `RunStep` row with `outcome=FAIL`, `error_message="expected 200 but got 500"`. Plus a mock `code.read` returning 1 commit per file path with SHA.
  - Register canned LLM responses for (a) category classification (REGRESSION); (b) draft diagnosis JSON.
  - Assert `defects` row created with `agent_diagnosis_kind=REGRESSION`, `agent_confidence > 0.6`, `agent_diagnosis` contains a commit SHA citation, `evidence_files` length > 0.
  - `test_diagnose_assist_does_not_file_tracker` — autonomy=assist; assert no tracker call made.
  - `test_diagnose_auto_files_tracker` — autonomy=auto; tracker.create_issue invoked once with payload matching diagnosis.
  - `test_diagnose_zero_tier_returns_503` — POST /agent/diagnose/runs/X with workspace ZERO → 503.
  - `test_diagnose_records_messages_and_cost`.

### 13.6 Commit

- [ ] **13.6.1** Commit: `feat(agent): AI diagnosis graph + auto-trigger on FAIL (Closes #M3-11)`.

---

## Task 14: CONVERSATION mode — AI panel chat

Lower-stakes; auto-picks smallest model from current provider. Read-only tools by default; mutations gated by explicit UI confirm.

### 14.1 Graph

- [ ] **14.1.1** Create `packages/agent/src/suitest_agent/graphs/conversation.py`:
  - Single-node loop: `chat_turn` → optional `invoke_tool` → `chat_turn` … until LLM returns no tool_calls.
  - Context window: last 20 turns + workspace context (current `route`, selected entity id) injected as system block.
  - Tools registered: `CONVERSATION_TOOLS`. Any mutating tool blocked at the registry layer (`mutates=True`) unless message metadata `{confirm: true}` accompanies the user turn from explicit UI click.

### 14.2 Model auto-pick

- [ ] **14.2.1** Helper `pick_conversation_model(provider: str) -> str`:
  - anthropic → `claude-haiku-4-5`
  - openai → `gpt-4o-mini`
  - gemini → `gemini-2.0-flash`
  - groq → `llama-3.1-8b`
  - openrouter → workspace-set conversation_model or `anthropic/claude-haiku-4-5`
  - bedrock → `anthropic.claude-haiku-4-5`
  - vertex → `gemini-2.0-flash`
  - deepseek → `deepseek-chat`
  - ollama → workspace-set conversation_model or `llama3.1`
  - other local → `llmconfig.config_json["conversation_model"]` if present else main model.

### 14.3 Endpoints

- [ ] **14.3.1** `POST /agent/sessions` body `{kind: "CONVERSATION", model_hint?, workspace_context?}` → creates session, returns `{sessionId}`.
- [ ] **14.3.2** `GET /agent/sessions/:id` → session + last 50 messages + tool calls.
- [ ] **14.3.3** `POST /agent/sessions/:id/messages` body `{role: "USER", content, confirm?}` → SSE stream of `agent.message.delta` + `agent.tool.*` events. Persists messages.
- [ ] **14.3.4** `POST /agent/sessions/:id/cancel` → sets `cancel_event`.

### 14.4 Tests

- [ ] **14.4.1** `packages/agent/tests/graphs/test_conversation.py`:
  - `test_conversation_picks_haiku_for_anthropic`.
  - `test_conversation_blocks_mutating_tool_without_confirm` — LLM tries `defect.create`; ctx without confirm → tool dispatch raises `MutationConfirmRequired`; graph translates to message asking user to confirm via UI.
  - `test_conversation_with_confirm_executes_mutation` — same as above but message has `confirm=True`; tool runs.
  - `test_conversation_context_window_limited_to_20_turns` — insert 30 history rows; assert LLM input messages truncated to last 20.
  - `test_conversation_session_persists_messages_and_tool_calls`.
- [ ] **14.4.2** `apps/api/tests/test_agent_sessions.py`:
  - `test_start_session_zero_tier_503`.
  - `test_send_message_streams_sse_deltas` — POST returns 200 + content-type `text/event-stream`; first frame `event: agent.session.started`.
  - `test_cancel_aborts_in_flight`.

### 14.5 Commit

- [ ] **14.5.1** Commit: `feat(agent,api): conversation mode + SSE messages endpoint (Closes #M3-12)`.

---

## Task 15: Streaming protocol — SSE + WS

Unify the streaming surface. SSE = token deltas (simple). WS = tool-call / approval events. Cancel via both.

### 15.1 SSE

- [ ] **15.1.1** All agent endpoints returning streams use `StreamingResponse(.., media_type="text/event-stream")` with heartbeat every 15s (`event: ping`).
- [ ] **15.1.2** Event names normalized per AI_AGENT.md §12:
  - `agent.session.started`
  - `agent.message.delta`
  - `agent.tool.start`
  - `agent.tool.input.delta`
  - `agent.tool.end`
  - `agent.case.created`
  - `agent.step.confirm_required`
  - `agent.diagnosis.ready`
  - `agent.session.completed`
  - `agent.session.cancelled`
  - `agent.session.error`

### 15.2 WS

- [ ] **15.2.1** Extend M1c WS router (`apps/api/src/suitest_api/routers/websocket.py`) with rooms `agent-session:<sessionId>` and `run:<runId>` for tool events.
- [ ] **15.2.2** Server-side pub/sub bridge: graphs publish events to Redis channel `agent-session:<id>`; WS subscribers fan out to clients.
- [ ] **15.2.3** Client→server `agent.cancel` message sets the session's cancel_event via Redis (`SET agent:<sessionId>:cancel 1` w/ TTL); server graphs poll this key OR receive via in-process pub/sub when cancellation is local.
- [ ] **15.2.4** Approval flow: server publishes `agent.step.confirm_required`; client publishes `agent.step.approve` / `agent.step.reject` / `agent.step.edit`; graph awaits with timeout.

### 15.3 FE hook

- [ ] **15.3.1** Create `apps/web/src/hooks/use-agent-stream.ts`:
  - Uses `@ai-sdk/react` `useChat` for SSE token streaming + own WS hook for tool/approval events.
  - Auto-reconnect WS on close; SSE reopens on user-resume after cancel.
  - Exposes `{messages, status, toolEvents, approve, reject, cancel}`.

### 15.4 Tests

- [ ] **15.4.1** `apps/api/tests/test_streaming_e2e.py` (httpx + aclient):
  - Start a conversation session (mock LLM canned content "hello"). Hit `POST /sessions/:id/messages`; assert SSE frames received: `started → delta x N → completed`.
  - Open WS connection to `agent-session:<id>`; trigger graph that calls a tool; assert WS received `agent.tool.start` + `agent.tool.end`.
  - Cancel via WS → server returns 200 on next SSE poll + final `agent.session.cancelled`.
- [ ] **15.4.2** `apps/web/src/hooks/__tests__/use-agent-stream.test.ts` (vitest + mock EventSource + mock WebSocket):
  - Token deltas accumulate into final message.
  - Tool event lands in `toolEvents` array.
  - Approval action posts to correct WS event.
  - Cancel disposes both connections.

### 15.5 Commit

- [ ] **15.5.1** Commit: `feat(api,web): unified SSE+WS streaming protocol for agent sessions (Closes #M3-13)`.

---

## Task 16: Autonomy levels — backend

Backend mechanics for autonomy CRUD, audit, per-feature overrides, safety rails.

### 16.1 Schemas

- [ ] **16.1.1** `packages/shared/suitest_shared/schemas/autonomy.py`:
  ```python
  from __future__ import annotations
  from pydantic import BaseModel, Field, field_validator
  from suitest_shared.domain.enums import AutonomyLevel, Tier

  KNOWN_OVERRIDE_KEYS = {
      "gen_finalize_p2p3", "gen_dedupe_auto_merge",
      "exec_agentic_no_prompt", "exec_self_heal_enabled",
      "exec_persist_translated",
      "diagnose_auto_categorize", "defect_auto_file",
      "defect_close_flaky", "flaky_auto_rerun",
      "code_export_on_failure", "auto_pr_fix",
  }

  class AutonomyPublic(BaseModel):
      level: AutonomyLevel
      overrides: dict[str, bool]
      effective: dict[str, str | bool]
      tier: Tier
      updated_at: str
      updated_by: str | None

  class AutonomyWrite(BaseModel):
      level: AutonomyLevel
      overrides: dict[str, bool] = Field(default_factory=dict)
      reason: str | None = None

      @field_validator("overrides")
      @classmethod
      def _valid_keys(cls, v: dict[str, bool]) -> dict[str, bool]:
          bad = set(v) - KNOWN_OVERRIDE_KEYS
          if bad:
              raise ValueError(f"unknown override keys: {sorted(bad)}")
          return v
  ```

### 16.2 Service

- [ ] **16.2.1** `packages/core/src/suitest_core/autonomy.py`:
  ```python
  from __future__ import annotations
  from suitest_shared.domain.enums import AutonomyLevel

  # Defaults from AUTONOMY.md §3 matrix.
  LEVEL_DEFAULTS: dict[AutonomyLevel, dict[str, bool | str]] = {
      AutonomyLevel.MANUAL: {
          "gen_create_status": "n/a",
          "exec_agentic_step": "skip",
          "diagnose_run_on_failure": False,
          "defect_auto_file": False,
          ...
      },
      AutonomyLevel.ASSIST: {
          "gen_create_status": "DRAFT",
          "exec_agentic_step": "confirm",
          "diagnose_run_on_failure": True,
          "defect_auto_file": True,
          "defect_close_flaky": False,
          "flaky_auto_rerun": "suggest",
          "auto_pr_fix": False,
          ...
      },
      AutonomyLevel.SEMI_AUTO: { ... },
      AutonomyLevel.AUTO:      { ... },
  }

  def effective(level: AutonomyLevel, overrides: dict[str, bool]) -> dict:
      base = dict(LEVEL_DEFAULTS[level])
      base.update(overrides)
      return base
  ```
- [ ] **16.2.2** `apps/api/src/suitest_api/services/autonomy_service.py`:
  - `get(db, workspace_id)`: load row + capability tier; compute `effective`.
  - `put(db, workspace_id, actor_user_id, body)`: validate `level ≤ tier_max_level` (ZERO → max manual); validate `auto_pr_fix=True` requires GitHub App integration installed (check `integrations` table). Insert `agent_autonomy_audit` row with before/after. Audit + commit + broadcast `capability.changed` WS event.
  - `audit_history(db, workspace_id, cursor, limit)`.
  - Always-enforced safety rails (per AUTONOMY.md §9): hardcoded constants exposed via `safety_rails()` helper used by tool dispatchers (Task 6, Task 13, Task 14).

### 16.3 Endpoints

- [ ] **16.3.1** Router `apps/api/src/suitest_api/routers/autonomy.py`:
  - `GET /workspaces/:id/autonomy` → `AutonomyPublic`.
  - `PUT /workspaces/:id/autonomy` → `AutonomyPublic` (admin only via `current_admin_user`).
  - `GET /workspaces/:id/autonomy/audit?cursor=…&limit=…` → paginated history.
  - Mount in `main.py`.

### 16.4 Tier-aware validation

- [ ] **16.4.1** PUT enforces:
  - Tier ZERO + level ≠ manual → 400 `AUTONOMY_REQUIRES_LLM`.
  - Overrides keys unknown → 422 via validator.
  - `auto_pr_fix=True` without GitHub App → 400 `OVERRIDE_REQUIRES_INTEGRATION`.

### 16.5 Tests

- [ ] **16.5.1** `apps/api/tests/test_autonomy.py`:
  - `test_get_returns_default_manual_for_fresh_workspace`.
  - `test_put_assist_writes_audit_and_broadcasts`.
  - `test_put_zero_tier_rejects_assist_400`.
  - `test_put_unknown_override_422`.
  - `test_put_auto_pr_fix_requires_gh_app_400`.
  - `test_audit_history_paginates_correctly`.
  - `test_effective_resolves_overrides_above_defaults`.
  - `test_safety_rails_enforced_even_in_auto` — autonomy=auto + override `defect_close_flaky=True`; calling close-defect-as-CLOSED still rejected by rail.

### 16.6 Commit

- [ ] **16.6.1** Commit: `feat(api,core): autonomy CRUD + audit + safety rails (Closes #M3-15)`.

---

## Task 17: Autonomy guards integrated into agent endpoints

Apply `require_autonomy` and per-feature override logic to every agent surface introduced in Tasks 8-14.

### 17.1 Endpoint guards

- [ ] **17.1.1** `POST /agent/generate/cases` → `require_tier(CLOUD|LOCAL)` + `require_autonomy(ASSIST)`.
- [ ] **17.1.2** `POST /agent/diagnose/runs/:id` → `require_tier(CLOUD|LOCAL)` + `require_autonomy(ASSIST)`.
- [ ] **17.1.3** `POST /agent/sessions/:id/messages` → `require_tier(CLOUD|LOCAL)`; conversation mode min autonomy `manual` (read-only) — composer is disabled at FE.
- [ ] **17.1.4** Action→code translation in runner — gated by `effective(autonomy)["exec_agentic_step"]` (skip in manual, prompt in assist, run in semi_auto/auto).

### 17.2 Per-priority auto-approval in generation

- [ ] **17.2.1** Implement `case_status_for_autonomy(level, priority, overrides) -> CaseStatus`:
  - manual → n/a (generation blocked)
  - assist → DRAFT (overrides cannot upgrade)
  - semi_auto → DRAFT if priority ∈ {P0,P1} else ACTIVE
  - auto → ACTIVE unless `gen_finalize_p2p3=False` override → DRAFT
- [ ] **17.2.2** Apply in `persist_drafts_node` of every GENERATION graph.

### 17.3 Diagnosis-driven actions per autonomy

- [ ] **17.3.1** In `diagnose.py` `persist_to_defect_node`:
  - assist → write diagnosis + leave defect OPEN, no tracker call.
  - semi_auto → write diagnosis + auto-create tracker issue; if category=FLAKE → enqueue auto-rerun (max 2).
  - auto → write diagnosis + auto-create tracker + auto-rerun + (defer auto-PR-fix to v2).

### 17.4 Tests

- [ ] **17.4.1** `apps/api/tests/test_agent_autonomy_integration.py`:
  - Matrix tests: for each (tier, autonomy) ∈ {(ZERO, manual), (CLOUD, manual), (CLOUD, assist), (CLOUD, semi_auto), (CLOUD, auto)}, drive `/agent/generate/cases`, assert: status code + case status + tracker side-effects per matrix.
  - `test_semi_auto_p0_case_stays_draft`.
  - `test_auto_with_override_finalize_p2p3_false_keeps_draft`.
  - `test_diagnose_assist_skips_tracker_call`.
  - `test_diagnose_auto_files_tracker_and_enqueues_rerun_on_flake`.

### 17.5 Commit

- [ ] **17.5.1** Commit: `feat(agent,api): autonomy-driven status + tracker side-effects (Closes #M3-16)`.

---

## Task 18: Settings → LLM UI

Page: `apps/web/src/routes/_app/settings/llm.tsx`. Always accessible (only escape hatch from ZERO).

### 18.1 Provider catalog

- [ ] **18.1.1** Create `apps/web/src/lib/llm-providers.ts`:
  ```ts
  export const PROVIDER_GROUPS = [
    { label: "Cloud", items: ["anthropic", "openai", "gemini", "groq",
                              "openrouter", "deepseek", "azure", "bedrock", "vertex"] },
    { label: "Local", items: ["ollama", "llamacpp", "vllm", "lmstudio"] },
    { label: "Off",   items: ["none"] },
  ] as const;
  ```
- [ ] **18.1.2** Backend `GET /llm-config/models?provider=anthropic` returns `[{id, name, contextWindow, costPer1kIn, costPer1kOut}]` from LiteLLM's known-model registry. Server-side helper `packages/agent/src/suitest_agent/providers/catalog.py` exposes the list per provider.

### 18.2 Form layout

- [ ] **18.2.1** Page `apps/web/src/routes/_app/settings/llm.tsx`:
  - Provider grouped Select (shadcn `<Select>` with `<SelectGroup>`).
  - API Key `<input type="password">` write-only with placeholder "Paste new key to update" — shows existing `api_key_hint` as helper text when set.
  - Model Select — lazy-loads on provider change.
  - Advanced collapsible (`<Accordion>`): temperature slider 0-2 (default 0.2), max_tokens (number, default 4096), base_url, timeout_ms, aws_region (Bedrock), gcp_project/location/credentials_path (Vertex).
  - "Test connection" button → POST `/workspaces/:id/llm-config/test` with form draft; result chip shows latency + first-token-ms + model echo.
  - "Save" → POST `/workspaces/:id/llm-config`; on success flash toast "AI features enabled" and trigger autonomy modal (Task 19.4).
  - "Reset to ZERO" destructive button → confirm dialog → DELETE.
  - Capability check banner if tier changed since last fetch.

### 18.3 State

- [ ] **18.3.1** Subscribe `useCapabilities()` Zustand store + listen WS `capability.changed`; re-render on tier change.

### 18.4 Tests

- [ ] **18.4.1** `apps/web/src/routes/_app/settings/__tests__/llm.test.tsx` (vitest + @testing-library/react + msw):
  - `renders provider groups`.
  - `lazy-loads models on provider change`.
  - `test connection ok shows latency chip`.
  - `test connection failure shows error message`.
  - `save calls PUT and shows autonomy upgrade prompt`.
  - `reset opens confirm and then calls DELETE`.
  - `existing config shows hint not key`.
- [ ] **18.4.2** Playwright E2E `apps/web/tests/e2e/settings-llm.spec.ts` — go to settings, set provider=anthropic + model + key, save, see tier badge flip from ZERO to CLOUD without page reload.

### 18.5 Commit

- [ ] **18.5.1** Commit: `feat(web): Settings → LLM page w/ live test connection + tier flip (Closes #M3-2.UI)`.

---

## Task 19: Settings → Automation UI

Page: `apps/web/src/routes/_app/settings/automation.tsx`. Hidden in ZERO (autonomy locked).

### 19.1 Layout

- [ ] **19.1.1** Page renders:
  - 4-card radio group (manual / assist / semi_auto / auto) with header + bullet copy from AUTONOMY.md §7.
  - Live `effective` preview re-computed client-side as user toggles.
  - Collapsible "Advanced overrides" — list every `KNOWN_OVERRIDE_KEYS` as `<Switch>`. Disabled with tooltip if pre-req missing (e.g. `auto_pr_fix` requires GitHub App).
  - Audit log link at bottom → `/settings/audit?action=autonomy.*`.
  - Save button → PUT `/workspaces/:id/autonomy`.

### 19.2 Typed-confirmation

- [ ] **19.2.1** Switching `assist` → `semi_auto` or `auto` opens modal that requires typing the exact string (per AUTONOMY.md §8.2). Downgrades single-click.
- [ ] **19.2.2** Server PUT re-validates the typed string from header `X-Suitest-Autonomy-Confirm`.

### 19.3 Upgrade modal (first-time LLM)

- [ ] **19.3.1** When `capability.changed` event observed with tier flipping ZERO→CLOUD/LOCAL AND user is workspace admin AND no autonomy row exists → show modal "AI is now available — choose starting mode" (per AUTONOMY.md §8.1). Options: Assist (recommended) / Semi-auto / Manual / Decide later.
- [ ] **19.3.2** Choice persists via PUT `/workspaces/:id/autonomy`. "Decide later" leaves at manual.

### 19.4 Tests

- [ ] **19.4.1** `apps/web/src/routes/_app/settings/__tests__/automation.test.tsx`:
  - `renders 4 cards with correct copy`.
  - `manual default selected when fresh workspace and CLOUD tier`.
  - `effective preview updates on override toggle`.
  - `upgrading to auto requires typed string`.
  - `downgrade single-click works`.
  - `auto_pr_fix disabled when no gh app integration`.
- [ ] **19.4.2** Playwright E2E `apps/web/tests/e2e/autonomy-modal.spec.ts` — after enabling LLM in settings, modal appears; choosing Assist persists; tier badge subtitle shows "assist".

### 19.5 Commit

- [ ] **19.5.1** Commit: `feat(web): Settings → Automation + upgrade modal (Closes #M3-15.UI)`.

---

## Task 20: AI panel wiring

`apps/web/src/components/shell/AiPanel.tsx` — replace M1b placeholder with real impl.

### 20.1 Library setup

- [ ] **20.1.1** Install `@ai-sdk/react@^1.0`, `assistant-ui@^0.5`, `eventsource-parser` for SSE parsing.
- [ ] **20.1.2** Customize `assistant-ui` theme via CSS variable overrides mapping to design tokens (per UI_SPEC.md §2.3).

### 20.2 AiPanel impl

- [ ] **20.2.1** AiPanel structure:
  - Header (47px) with agent avatar, name, subtitle `${provider}:${model} · ${autonomy} · N sessions`, history + more icons.
  - Mode tabs: Agent / Generate / Ask.
  - Thread (assistant-ui `<Thread>`).
  - Composer (sticky bottom). Disabled with tooltip when `autonomy === "manual"`.
- [ ] **20.2.2** Use `useAgentStream()` hook from Task 15. On each turn:
  - POST `/agent/sessions` (lazy session creation) if no session yet.
  - POST `/agent/sessions/:id/messages` → SSE → render tokens into thread.
  - WS subscribe `agent-session:<sessionId>` for tool events.
  - Render inline `<ToolCallCard>` per tool event (terminal-style, mono, provider name `via playwright-mcp`).
  - Render inline `<ApprovalCard>` when `agent.step.confirm_required` received in assist mode; buttons Approve / Reject / Edit args.
- [ ] **20.2.3** Cancel button → POST `/agent/sessions/:id/cancel` + close streams.
- [ ] **20.2.4** `capability.changed` listener: refetch `/capabilities`; if AI now available, AiPanel becomes mountable mid-session without reload.

### 20.3 Conditional rendering

- [ ] **20.3.1** `useCapabilities()` returns `{tier, autonomy, features}`. AiPanel renders only when `tier !== "ZERO"`. In ZERO the root grid drops the right column (per UI_SPEC.md §2.3).
- [ ] **20.3.2** Composer disabled when `autonomy === "manual"` with `<DisabledTooltip reason="Switch to assist mode to enable composer">`.

### 20.4 Tests

- [ ] **20.4.1** `apps/web/src/components/shell/__tests__/AiPanel.test.tsx` (vitest + mock EventSource + mock WS):
  - `hidden in ZERO`.
  - `composer disabled in manual`.
  - `streams tokens into thread`.
  - `renders approval card on confirm_required event`.
  - `clicking approve posts agent.step.approve over WS`.
  - `cancel button stops stream`.
  - `capability.changed mid-session updates subtitle and re-renders`.
- [ ] **20.4.2** Playwright E2E `apps/web/tests/e2e/ai-panel.spec.ts` — CLOUD workspace, send "list my test cases", see tool call card for `db.query_cases`, then a final answer with case list.

### 20.5 Commit

- [ ] **20.5.1** Commit: `feat(web): AI panel real impl w/ assistant-ui + approval cards (Closes #M3-12.UI)`.

---

## Task 21: Cost tracking + budget guard (lite)

Persist per-call cost; aggregate; soft-warn at 80%, hard-stop at 100%.

### 21.1 Persistence

- [ ] **21.1.1** Extend `LiteLLMRouter.complete/stream` to return cost; caller (each graph) accumulates and updates `AgentSession.cost_usd` + `tokens_in` + `tokens_out` per-message.
- [ ] **21.1.2** Add helper `record_llm_call(db, session_id, cost, tokens_in, tokens_out)` in `agent_session_repo`. Called once per LLM call.

### 21.2 Budget guard

- [ ] **21.2.1** Create `packages/agent/src/suitest_agent/providers/budget.py`:
  ```python
  from __future__ import annotations
  from decimal import Decimal
  from fastapi import HTTPException
  from suitest_db.repositories.budget_repo import get_by_workspace, sum_cost_today

  async def enforce(workspace_id: str, *, db) -> None:
      budget = await get_by_workspace(db, workspace_id)
      if budget is None:
          return    # no budget set → unbounded
      today = await sum_cost_today(db, workspace_id)
      hard = budget.daily_usd * budget.hard_cap_pct
      if today >= hard:
          raise HTTPException(429, {"error": {
              "code": "BUDGET_EXCEEDED",
              "message": f"Daily budget hit (${today} / ${budget.daily_usd}). "
                         f"Raise limit or wait until tomorrow.",
              "details": {"today": str(today), "limit": str(budget.daily_usd)},
          }})
  ```
- [ ] **21.2.2** Wire `enforce()` as a FastAPI dependency `require_budget(workspace_id, db)`. Apply to every agent endpoint that initiates LLM calls (`/agent/generate/cases`, `/agent/diagnose/*`, `/agent/sessions/:id/messages`).
- [ ] **21.2.3** Soft-cap (80%): when reached, downgrade model via `budget.downgrade_map_json`. Caller mutates `router.cfg.model` per session start. Hook helper `maybe_downgrade(cfg, today, budget)`.

### 21.3 Daily aggregator job

- [ ] **21.3.1** ARQ scheduled job `aggregate_daily_cost` runs hourly. Computes `(workspace_id, day, provider, mode) → sum(cost_usd)` and stores rolling snapshot in `workspace_capabilities.features_json["cost_today"]` for cheap reads by `/capabilities`.

### 21.4 Tests

- [ ] **21.4.1** `packages/agent/tests/providers/test_budget.py`:
  - `test_enforce_no_budget_set_passes`.
  - `test_enforce_below_soft_cap_passes`.
  - `test_enforce_above_hard_cap_429`.
  - `test_soft_cap_swaps_model` — workspace usage at 85% of $5 budget → router cfg.model rewrites from sonnet to haiku.
  - `test_aggregator_writes_capability_features_json`.
- [ ] **21.4.2** `apps/api/tests/test_agent_budget.py`:
  - Drive `/agent/generate/cases` after seeding 24h cost of $5.01 → 429.

### 21.5 FE wiring

- [ ] **21.5.1** Run detail head + Generate modal show `<CostChip>` with last-session cost.
- [ ] **21.5.2** Workspace store includes `costToday` from capabilities; `<TierBadge>` popover shows it.

### 21.6 Commit

- [ ] **21.6.1** Commit: `feat(agent,api): per-session cost + budget guard + downgrade map (Closes #M3-14)`.

---

## Task 22: Reproducibility — session replay

Backend-ready endpoint for read-only step-through. Time-travel UI deferred to M4.

### 22.1 Endpoint

- [ ] **22.1.1** Add `GET /agent/sessions/:id/replay` → returns:
  ```json
  {
    "session": { "id": "...", "provider": "...", "model": "...",
                  "promptVersionId": "...", "seed": 42, "temperature": 0.2,
                  "ragChunks": [{"chunkId": "...", "sha256": "..."}],
                  "startedAt": "...", "completedAt": "...", "costUsd": "0.043" },
    "messages": [...],         // ordered AgentMessage rows
    "toolCalls": [...]         // ordered AgentToolCall rows
  }
  ```
- [ ] **22.1.2** `POST /agent/sessions/:id/replay?dry_run=true` — re-runs the graph against the same provider+model+seed (best-effort determinism). Returns diff vs. recorded outputs. **Read-only — does not mutate DB.**

### 22.2 Service

- [ ] **22.2.1** `apps/api/src/suitest_api/services/agent_replay_service.py` — `read_replay(db, session_id)` joins session + messages + tool_calls; returns Pydantic envelope.

### 22.3 Tests

- [ ] **22.3.1** `apps/api/tests/test_agent_replay.py`:
  - Seed a completed session with 3 messages + 2 tool calls; GET → all fields present + ordered.
  - `test_replay_dry_run_reproduces_output_when_seed_set` — using MockRouter and same seed, dry-run output equals original message content.
  - `test_replay_cross_workspace_404`.

### 22.4 Commit

- [ ] **22.4.1** Commit: `feat(api): session replay endpoint (read-only) for reproducibility (Closes #M3-5.replay)`.

---

## Task 23: Generation modal UI — AI strategies enabled

Wire M2's modal to AI flows when tier supports it.

### 23.1 Strategy radio

- [ ] **23.1.1** In `apps/web/src/components/cases/GenerateModal.tsx`:
  - Step 4 (Strategy) radio:
    - Deterministic — always enabled.
    - AI-enrich — enabled iff `features.ai_generation`.
    - AI-only — enabled iff `features.ai_generation`.
  - When disabled, `<DisabledTooltip reason="Requires LLM provider — configure in Settings → LLM" />`.
- [ ] **23.1.2** Footer left: `<CostChip>` showing estimated cost computed from `tokens_estimate × providerRate` (helper `estimate-cost.ts`). Hidden when Deterministic.

### 23.2 Wiring

- [ ] **23.2.1** On submit with AI strategy → POST `/agent/generate/cases` with `{source, targetSuiteId, targetKind, mcpProviderId, strategy, input, options}`.
- [ ] **23.2.2** SSE consumed via EventSource; each `event: case` prepends to step-5 list with slide-in animation.
- [ ] **23.2.3** `event: complete` → swap Generate primary button to "Add N to suite" (POSTs to `/test-cases` batch).
- [ ] **23.2.4** Errors:
  - 503 `LLM_DISABLED` → inline banner + button "Configure LLM".
  - 429 `BUDGET_EXCEEDED` → modal-level banner.
  - 403 `AUTONOMY_LEVEL_INSUFFICIENT` → inline banner "Upgrade autonomy in Settings → Automation".

### 23.3 Tests

- [ ] **23.3.1** `apps/web/src/components/cases/__tests__/GenerateModal-ai.test.tsx`:
  - `ai radios disabled in zero with tooltip`.
  - `ai radios enabled in cloud`.
  - `submit ai_only posts to agent endpoint`.
  - `streaming cases prepend to step 5 list`.
  - `complete event swaps button label`.
  - `budget_exceeded shows banner`.
- [ ] **23.3.2** Playwright E2E `apps/web/tests/e2e/generate-ai.spec.ts` — CLOUD workspace; open modal; choose Backend API; paste OpenAPI URL; pick AI-enrich; assert at least 1 case streams + appears + can be added to suite.

### 23.4 Commit

- [ ] **23.4.1** Commit: `feat(web): GenerateModal AI strategies wired to /agent/generate/cases (Closes #M3-6.UI #M3-8.UI)`.

---

## Task 24: Diagnosis UI replacement

Run detail page swaps the M1d "Manual triage needed" card for "Agent Diagnosis" violet card when capability supports it.

### 24.1 Components

- [ ] **24.1.1** `apps/web/src/components/runs/AgentDiagnosisCard.tsx`:
  - Violet-tinted card with sparkle icon.
  - Body: root cause statement + `<ConfidenceBadge value={confidence}>` (High/Med/Low + percent) + evidence bullets (clickable, jump to log/stack frame) + "Suggested fix" snippet (Monaco read-only) + actions (`<Button>File defect</Button>` / `Mark flaky` / `Dispute diagnosis`).
- [ ] **24.1.2** `apps/web/src/components/runs/ManualTriageCard.tsx` — already in M1d. Keep for ZERO.

### 24.2 Conditional rendering

- [ ] **24.2.1** Run detail step view:
  - If `step.outcome === "FAIL"` AND `features.ai_diagnose` → render `<AgentDiagnosisCard>` (data from `defects.agent_diagnosis*` columns).
  - Else → `<ManualTriageCard>`.
  - If diagnosis is still pending (autonomy=assist on-demand mode) → button "Diagnose with AI" → POST `/agent/diagnose/runs/:id`.

### 24.3 Dispute flow

- [ ] **24.3.1** "Dispute diagnosis" opens drawer with text area; submit → audit log + sets `defects.agent_diagnosis_kind=MANUAL_TRIAGE` + clears confidence. New `audit_log` row with `action="diagnosis.disputed"`.

### 24.4 Apply suggested fix (placeholder)

- [ ] **24.4.1** "Apply suggested fix" button → opens read-only diff viewer (Monaco DiffEditor) of the proposed `step.code` change vs current. **Commit/PR creation deferred to v2 PR-codegen.**

### 24.5 Tests

- [ ] **24.5.1** `apps/web/src/components/runs/__tests__/diagnosis.test.tsx`:
  - `renders manual triage card in zero`.
  - `renders agent diagnosis card in cloud with confidence and evidence`.
  - `clicking diagnose button triggers POST on demand`.
  - `dispute opens drawer and submits with reason`.
  - `apply suggested fix opens diff viewer in read-only mode`.

### 24.6 Commit

- [ ] **24.6.1** Commit: `feat(web): AgentDiagnosisCard for CLOUD/LOCAL runs (Closes #M3-11.UI)`.

---

## Task 25: DoD smoke test

End-to-end manual journey + automated smoke. Tag the candidate release.

### 25.1 Manual smoke journey (documented + run)

- [ ] **25.1.1** Document journey in `apps/api/tests/manual/M3_smoke.md`:
  1. Start ZERO workspace `Nusantara Retail` (from M0 + M1a seed).
  2. Verify topbar shows `ZERO`, AI panel hidden, Generate split-button has only deterministic options enabled.
  3. Settings → LLM: pick `anthropic`, paste `sk-ant-…` key, pick `claude-sonnet-4-5`, Test connection (assert latency chip).
  4. Save → assert toast "AI features enabled" + autonomy upgrade modal appears.
  5. Choose `assist`. Modal closes. Topbar badge flips to `CLOUD · anthropic:claude-sonnet-4-5` without reload (capability.changed WS event).
  6. AI panel visible. Send "list my test cases" → tool call `db.query_cases` card appears in thread → list returned. Verify cost chip shows tokens + cost.
  7. Generate modal: choose Mixed PRD → paste 3-paragraph PRD blob (file `tests/fixtures/prds/checkout-001.md`) → AI-only strategy → Generate. Assert 5 cases stream into step 5 list as `event: case`. All cases status DRAFT (assist autonomy).
  8. Select 3 cases, click "Add 3 to suite". Cases appear in suite tree.
  9. Run all 3 cases. 2 pass, 1 fails (intentional bad fixture). On failure → AI diagnosis card populates within 30s with `REGRESSION` category + confidence ≥ 0.6 + ≥1 commit citation.
  10. Workspace billing chip in topbar popover shows total spend > $0.
- [ ] **25.1.2** Manual journey performed; screenshots attached to `apps/api/tests/manual/M3_smoke_screenshots/`.

### 25.2 Automated smoke test

- [ ] **25.2.1** Create `apps/api/tests/smoke/test_m3_e2e.py` (pytest-asyncio):
  - Fixture: empty workspace, MockRouter w/ canned: (a) `db.query_cases` response, (b) story extraction returning 3 stories, (c) 5 draft case JSONs, (d) diagnosis JSON returning REGRESSION confidence 0.72 + commit SHA.
  - Step 1: POST /llm-config { mock } → 200 + tier flips to "CLOUD" (mock provider mapped to CLOUD by config).
  - Step 2: PUT /autonomy { level: assist } → 200.
  - Step 3: GET /capabilities → assert tier=CLOUD, autonomy=assist, features.ai_*=true.
  - Step 4: POST /agent/generate/cases { source: PRD, ... } → SSE bytes parsed → assert 5 `event: case` frames + 1 `event: complete`.
  - Step 5: persist 3 cases via POST /test-cases batch.
  - Step 6: POST /test-cases/:id/run for 1 case w/ guaranteed-failing fixture step → run completes with FAIL.
  - Step 7: ARQ test-mode flushes; assert defect row populated w/ agent_diagnosis_kind=REGRESSION + confidence > 0.6 + agent_diagnosis contains commit SHA.
  - Step 8: GET /capabilities → cost_today > 0.
- [ ] **25.2.2** Add CI job `m3-e2e` running this test against fresh Postgres + Redis + MinIO.

### 25.3 ZERO regression smoke

- [ ] **25.3.1** Re-run M0+M1+M2 ZERO smoke suite: confirm no LLM call made, no `503 LLM_DISABLED` on deterministic endpoints, AI panel hidden, generate modal deterministic strategy works.

### 25.4 Release candidate tag

- [ ] **25.4.1** Update `CHANGELOG.md` with M3 highlights.
- [ ] **25.4.2** Bump version in `apps/api/pyproject.toml` + `apps/web/package.json` to `0.7.0`.
- [ ] **25.4.3** `git tag v0.7.0-m3` after CI green.

### 25.5 Commit

- [ ] **25.5.1** Commit: `chore(release): v0.7.0-m3 candidate (Closes #M3-DoD)`.

---

## Definition of Done

All of the following must be true before declaring M3 complete:

1. **M3-1 LiteLLM router** — single chokepoint, 5+ providers replay green from VCR cassettes.
2. **M3-2 LLM config + AES-GCM** — Settings → LLM saves encrypted key, test-connection works, tier resolver re-emits `capability.changed`.
3. **M3-3 Tier resolver refresh** — flipping LLM config without process restart triggers `WorkspaceCapability` row refresh + WS broadcast.
4. **M3-4 LangGraph 4 modes** — GENERATION, EXECUTION, DIAGNOSIS, CONVERSATION graphs all compile, run, and persist checkpoints. Each graph has tests using MockRouter.
5. **M3-5 Reproducibility** — every `AgentSession` row carries `prompt_version_id`, `model_id`, `provider`, `seed`, `temperature`, `messages`, `tool_call_trace`, `cost_usd`. Replay endpoint reconstructs full event sequence.
6. **M3-6 PRD generator** — `/agent/generate/cases?source=PRD` streams 3-5 cases against test fixture PRDs.
7. **M3-7 URL semantic generator** — `/agent/generate/cases?source=URL_SEMANTIC` produces cases via browser-use-mcp.
8. **M3-8 OpenAPI enrich** — hybrid deterministic + AI; falls back gracefully on LLM failure.
9. **M3-9 MCP discovery generator** — connects to user-registered MCP, exercises tools.
10. **M3-10 Action→code translation** — runner translates action-only steps at runtime in CLOUD/LOCAL; still SKIPS in ZERO.
11. **M3-11 AI diagnosis** — replaces M1d MANUAL_TRIAGE in CLOUD/LOCAL; auto-fires on FAIL; persists structured output.
12. **M3-12 AI panel chat** — assistant-ui-based panel streams tokens + renders tool calls + supports approval cards in assist.
13. **M3-13 Streaming** — SSE for tokens, WS for tool/approval events; cancel works; reconnect works.
14. **M3-14 Cost tracking + budget guard** — per-session cost persisted; 80%/100% caps enforced; downgrade map active.
15. **M3-15 Autonomy levels** — 4 levels CRUD'd via API + UI; audit log written; safety rails enforced.
16. **M3-16 Per-feature overrides** — `KNOWN_OVERRIDE_KEYS` accepted; effective behavior computed and surfaced.
17. **ZERO regression** — all M0-M2 functionality still green; no LLM call made in ZERO; AI features all `<Gated>`.
18. **Manual smoke** — DoD journey in Task 25 passes top-to-bottom against `anthropic` provider.
19. **Automated smoke** — `m3-e2e` CI job green.
20. **No placeholders** — every `TODO`, `pass`, `NotImplementedError` removed from new modules; all sub-step commits CI-green.

---

## Self-review checklist (before opening final PR)

- [ ] All M3-1 through M3-16 acceptance criteria from `ROADMAP.md` covered by tasks + tests.
- [ ] 4 agent modes implemented as LangGraph state machines (Tasks 8, 9, 10, 11, 12, 13, 14).
- [ ] 4 LLM-driven generation sources wired into `/agent/generate/cases` (PRD, URL_SEMANTIC, MCP_DISCOVERY, OPENAPI_ENRICH).
- [ ] Autonomy levels enforced at API (DI guards) + UI (DisabledTooltip + composer disable).
- [ ] Cost tracked per session; 80%/100% budget caps enforced; downgrade map exercised by test.
- [ ] Reproducibility metadata persisted on `agent_sessions`: model, prompt_version_id, seed, temperature, messages (via AgentMessage rows), tool calls (via AgentToolCall rows), rag_chunks_json.
- [ ] ZERO tier still works untouched — verified by re-running M0-M2 smoke suites.
- [ ] No placeholders, no `pass`, no `TODO(M3): ...` strings in new modules.
- [ ] VCR cassettes scrub all secrets; cassettes committed; CI replay-only by default.
- [ ] Mock provider is the unit-test default; unknown fingerprints raise loudly.
- [ ] AES-GCM master key sourced from `SUITEST_ENCRYPTION_KEY` env (M1a) — never hardcoded.
- [ ] Every audit log row sets `actor_type='agent'`+`correlation_id=session_id`+`autonomy_level_at_time` for agent-initiated mutations.
- [ ] Safety rails (no autonomous delete, no defect CLOSED, no push to main) enforced regardless of autonomy/overrides; covered by tests.
- [ ] CHANGELOG.md updated; version bumped to `0.7.0`; tag `v0.7.0-m3` placed.

---

## Open questions / spec gaps surfaced during planning

1. **MockProvider tier mapping** — Task 3.5 `test_put_unsupported_provider_400` uses `mock` as a real provider option to drive automated CI smoke. Spec (`CAPABILITY_TIERS.md` §2) lists provider sets per tier but does not explicitly bucket `mock`. **Resolution adopted in this plan**: `mock` maps to CLOUD tier for the purposes of tier resolution and is accepted by `SUPPORTED_PROVIDERS`; document this in CAPABILITY_TIERS.md follow-up. Surfaced as a non-blocking spec gap.

2. **`DiagnosisKind` enum values** — AI_AGENT.md §10 defines `REGRESSION | FLAKE | INFRA | SPEC_DRIFT | MANUAL_TRIAGE`. DATA_MODEL.md §3.7 references the enum without enumerating values. Task 13 (13.3.1) assumes those exact 5 values; if the existing M1d enum is narrower, an Alembic migration to widen it lands in Task 0.

3. **Conversation model name catalog** — Task 14.2 hardcodes the "smallest model" per provider. These names may shift between LiteLLM releases. **Resolution**: model picks live in `packages/agent/providers/catalog.py` as a single dictionary editable without code changes; revisit at M4 with a fallback chain.

4. **Approval card timeout** — Task 12.3.1 fixes 5min; AI_AGENT.md §9 says "5-minute timeout". Aligned.

5. **Anthropic prompt caching** — Task 1 adds an `anthropic_cache_block` helper; per-prompt usage left to graph node implementations to apply on system messages + RAG chunks. No spec gap, but worth a follow-up dedicated micro-task post-M3 for measured cache-hit telemetry.

6. **Budget downgrade map default** — Task 21 default map covers anthropic / openai / gemini / ollama. Other providers fall through (no swap). Acceptable for v1.0; revisit M4.

7. **Replay determinism for providers without seed support** — Task 22.1.2 admits "best-effort determinism". Anthropic in particular does not expose a seed; replays will diff. Documented in `apps/api/tests/manual/M3_smoke.md` and the replay endpoint response includes a `determinism: "seed_supported" | "best_effort"` flag.

8. **PromptVersion content drift policy** — Task 5.3.1 raises `PromptVersionContentDrift` when the same `(name, version)` is re-loaded with different content. Forces coder to bump `version`. No spec gap; documented in plan.

9. **Per-workspace conversation model override** — `LLMConfig.config_json["conversation_model"]` is read by Task 14.2 helper. Need to document in `API.md §3.14` so SDK users know they can set it. Logged as follow-up doc task.

10. **`/llm-config/models` endpoint** — surfaces LiteLLM's model catalog per provider (Task 18.1.2). Not currently in `API.md §3.14`. Will be added in the same PR that introduces Task 18.

---

## Cross-references

- `docs/superpowers/specs/2026-05-26-suitest-oss-pivot-design.md` — pivot memo (source of truth)
- `docs/ROADMAP.md` §M3 — acceptance criteria source
- `docs/AI_AGENT.md` — LiteLLM + LangGraph architecture + 4 modes + prompts + tools
- `docs/CAPABILITY_TIERS.md` — tier resolver + gating policy
- `docs/AUTONOMY.md` — 4 levels + overrides + safety rails
- `docs/GENERATORS.md` §5 — LLM-driven generators (PRD, URL semantic, MCP discovery, OpenAPI enrich)
- `docs/UI_SPEC.md` §3.7.5, §3.7.6, §2.3 — Settings LLM, Settings Automation, AI panel
- `docs/API.md` §3.10, §3.14, §3.15 — agent endpoints, LLM config, autonomy
- `docs/DATA_MODEL.md` §3.9, §4.1, §4.2, §4.5 — agent sessions, llm_configs, workspace_capabilities, prompt_versions
- `docs/superpowers/plans/2026-05-26-plan-04-m1c-runner-mcp.md` §11 — step executor TODO that Task 12 rewires
- `docs/superpowers/plans/2026-05-26-plan-05-m1d-tcm-writes.md` — rule-based diagnosis that Task 13 replaces in CLOUD/LOCAL
- `docs/superpowers/plans/2026-05-26-plan-06-m2-generators-mcp-expansion.md` — deterministic generators that Task 11 enriches
