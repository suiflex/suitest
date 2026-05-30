# M4 — LOCAL Tier + Ship Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate LOCAL tier (Ollama, llamacpp, vllm, lmstudio) end-to-end; add `fastembed` local embeddings enabling semantic search in ZERO+fastembed combo; harden Helm chart for production with HPA/probes/PDB/NetworkPolicy; validate air-gapped k8s deploy with zero outbound network; ship `suitest-py` (PyPI) + `@suitest/sdk` (npm) + `suitest` CLI; build eval harness backend with golden fixtures; build cost dashboard UI; build time-travel run replay UI; complete observability (OpenTelemetry + Prometheus + optional Langfuse); i18n English + Bahasa Indonesia; a11y axe pass; documentation site (Astro Starlight); 4 example projects; dogfood Suitest tests Suitest in CI; ship readiness: Apache 2.0 LICENSE + CONTRIBUTING + CODE_OF_CONDUCT + SECURITY + ISSUE_TEMPLATEs; tag v1.0.0.

**Architecture:** LOCAL providers configured via `base_url` override in LiteLLM (Ollama=`http://ollama:11434`, llamacpp=`http://llamacpp:8080/v1`, vllm=`http://vllm:8000/v1`, lmstudio=`http://lmstudio:1234/v1`). `fastembed` runs in-process (CPU, ~130MB BAAI/bge-small model) inside `apps/api` for embeddings — toggled via `SUITEST_EMBEDDINGS_BACKEND=fastembed`. Helm chart production layer adds HPA via KEDA (queue-depth metric for runner; cpu/mem for api/web), PodDisruptionBudget, NetworkPolicy (default-deny + explicit allowlist), Ingress with cert-manager, optional bundled Postgres+Redis+MinIO via subcharts. Air-gapped: image registry mirror, no outbound DNS; bundled MCP binaries in api image. SDKs auto-generated from FastAPI's `/openapi.json` (committed to `packages/shared/openapi.json` on release). CLI = `suitest` Python entrypoint via `uv` packaging. Eval harness backend stores fixtures in `eval/fixtures/{prds,openapi,failed_runs}/`, run via ARQ scheduled job weekly. Time-travel UI uses `/agent/sessions/:id/replay` from M3 + diff viewer per step. Observability: OpenTelemetry SDK auto-instruments FastAPI/SQLAlchemy/httpx/asyncpg exporting to OTLP HTTP (Honeycomb/Grafana Cloud/self-host Tempo); Prometheus `/metrics` scraped by ServiceMonitor; Sentry SDK for web+api; optional Langfuse compose service for LLM-call audit.

**Tech Stack:** Python 3.12, `fastembed` (Qdrant team), `kubernetes-asyncio`, KEDA, cert-manager, Helm 3, `openapi-python-client`, `openapi-typescript-codegen`, `typer` for CLI, `uv` for packaging, Astro Starlight for docs site, `axe-core` for a11y, `react-i18next` for i18n, OpenTelemetry SDK Python + JS, prometheus-fastapi-instrumentator (from M1a), Sentry SDK, Langfuse SDK (optional).

---

## Prerequisites

Before starting M4, verify:

- **M0** complete — monorepo bootable, `docker compose --profile zero up -d` brings full stack, ZERO-tier `GET /capabilities` returning `{tier: "ZERO", autonomy: "manual", llm_provider: null}`, Helm chart skeleton lints.
- **M1a** complete — read-only REST endpoints, workspace scoping, audit log helper, full seed (Nusantara Retail), Prometheus `/metrics` exposed via `prometheus-fastapi-instrumentator`.
- **M1b** complete — read-only UI screens wired, `<Gated>`, `<TierBadge>`, `useCapabilities()` Zustand store, Lighthouse CI gate.
- **M1c** complete — `packages/mcp` registry/client/pool, `apps/runner` ARQ worker, WebSocket log streaming, MinIO artifacts.
- **M1d** complete — Test case writes, suite CRUD, manual + rule-based defect, integrations (Jira/Linear/GitHub), Slack notifications.
- **M2** complete — 3 deterministic generators (OpenAPI, Recorder, Crawler), 5 additional bundled MCPs (graphql/mongo/mysql/k8s/grpc), custom MCP registration, code export.
- **M3** complete — LiteLLM router, `LLMConfig` AES-GCM, LangGraph 4 modes (generation/execution/diagnosis/conversation), versioned prompts + reproducibility (prompt_version_id/model_id/seed/temperature), PRD/URL-semantic/MCP-discovery generators, action→code runtime translate, AI diagnosis, assistant-ui chat panel, SSE token stream, cost tracking, autonomy levels (manual/assist/semi_auto/auto) + Settings → Automation page.
- **9+ CLOUD providers tested** in M3 (anthropic, openai, gemini, groq, openrouter, azure, bedrock, vertex, deepseek).
- **DB tables present**: `eval_runs`, `eval_fixtures`, `cost_aggregates` placeholders may need fresh Alembic migrations as Task 0 if not added in M3.

If any prerequisite is missing, stop and complete that milestone first.

---

## Conventions for this plan

- **TDD always.** Each backend task: (1) write failing pytest, (2) implement, (3) green test, (4) refactor. Each frontend task: vitest unit tests + Playwright E2E where flows are observable. Helm template tasks: `helm template` + `helm lint` + `kubeconform` (strict schema validation against k8s schemas).
- **Conventional commits per sub-step** with milestone reference: `feat(local): wire ollama backend (Closes #M4-1)`, `feat(helm): KEDA scaledobject for runner (Closes #M4-3)`, etc.
- **Pydantic v2** for all API I/O. Domain models in `packages/shared/suitest_shared/schemas/`. SQLAlchemy 2.0 async ORM in `packages/db/suitest_db/models/`.
- **mypy strict** with `disallow_untyped_defs=true`. No `Any` — use `TypedDict`, `Protocol`, generics. No `as any` in TypeScript.
- **No barrel files.** Direct imports only.
- **Capability gate** every endpoint declares `Depends(require_tier(...))`. Eval harness endpoints declare `require_tier(Tier.LOCAL | Tier.CLOUD)` because evaluating an agent obviously requires an LLM; deterministic fixtures may be added in v1.x.
- **Audit log** every mutation through `packages/db/audit.py::write_audit`.
- **OpenTelemetry** spans wrap every cross-process boundary. Span attrs include `workspace_id`, `tier`, `autonomy`, `model_id`, `provider`.
- **Workspace scoping** is mandatory. Cross-workspace access returns 404.
- **No mock data leaks to prod.** Eval fixtures live under `eval/fixtures/` outside repo root only when explicitly opted-in by `SUITEST_EVAL_ENABLED=1`.
- **Helm values** every new key documented inline in `values.yaml` + reflected in `docs/DEPLOYMENT.md` table.
- **Air-gap discipline.** No task may add a hard external network dependency that breaks `tier=zero, networkPolicy.egress.allowLLM=false`.
- Each numbered task ends with a `git commit`. Some tasks have multiple sub-step commits — each sub-step commit is independent and CI-green.

---

## Task 0: Migration prep — `eval_runs`, `eval_fixtures`, `cost_aggregates`, `i18n_preferences`

Verify the new tables; if not present from M3, add a migration as Task 0.

- [ ] **0.1** Run `uv run alembic heads` and `uv run alembic history --indicate-current`. Confirm M3 head exists. Capture revision id as `<m3_head>`.
- [ ] **0.2** Create migration `packages/db/suitest_db/migrations/versions/2026_05_26_m4_eval_cost_i18n.py`:
  - `revision = "m4_eval_cost_i18n"`
  - `down_revision = "<m3_head>"`
  - `upgrade()` creates:
    - `eval_runs(id text PK, workspace_id text FK→workspaces(id) ON DELETE CASCADE, suite_name text NOT NULL, fixture_set text NOT NULL, started_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz NULL, status text NOT NULL DEFAULT 'running', total_fixtures int NOT NULL DEFAULT 0, passed int NOT NULL DEFAULT 0, failed int NOT NULL DEFAULT 0, regressions int NOT NULL DEFAULT 0, score_json jsonb NOT NULL DEFAULT '{}'::jsonb, model_id text NULL, provider text NULL, cost_usd numeric(10,4) NOT NULL DEFAULT 0, created_by_user_id uuid NULL FK→users(id))`
    - Index `ix_eval_runs_workspace_started` ON (workspace_id, started_at DESC)
    - Index `ix_eval_runs_status` ON (status) WHERE status = 'running'
    - `eval_fixtures(id text PK, kind text NOT NULL, name text NOT NULL UNIQUE, path text NOT NULL, expected_json jsonb NOT NULL, version text NOT NULL DEFAULT 'v1', tags text[] NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now())` — `kind` CHECK IN ('prd','openapi','failed_run')
    - `cost_aggregates(id text PK, workspace_id text FK→workspaces(id) ON DELETE CASCADE, bucket_date date NOT NULL, provider text NOT NULL, model_id text NOT NULL, kind text NOT NULL, tokens_in bigint NOT NULL DEFAULT 0, tokens_out bigint NOT NULL DEFAULT 0, cost_usd numeric(12,4) NOT NULL DEFAULT 0, session_count int NOT NULL DEFAULT 0, UNIQUE(workspace_id, bucket_date, provider, model_id, kind))` — `kind` CHECK IN ('GENERATION','EXECUTION','DIAGNOSIS','CONVERSATION','EVAL')
    - Index `ix_cost_aggregates_workspace_date` ON (workspace_id, bucket_date DESC)
    - `i18n_preferences(user_id uuid PK FK→users(id) ON DELETE CASCADE, locale text NOT NULL DEFAULT 'en', updated_at timestamptz NOT NULL DEFAULT now())` — `locale` CHECK IN ('en','id')
    - `budget_configs(workspace_id text PK FK→workspaces(id) ON DELETE CASCADE, daily_cap_usd numeric(10,2) NOT NULL DEFAULT 50, soft_warn_pct int NOT NULL DEFAULT 80, hard_stop boolean NOT NULL DEFAULT false, slack_webhook_url text NULL, updated_at timestamptz NOT NULL DEFAULT now(), updated_by_user_id uuid NULL FK→users(id))`
  - `downgrade()` drops in reverse order.
- [ ] **0.3** Write pytest `packages/db/tests/test_migration_m4.py`:
  - Apply migration → verify each table via `inspector.get_table_names()`.
  - Verify indexes + CHECK constraints (insert violating row → expect IntegrityError).
  - Downgrade → tables removed.
- [ ] **0.4** `uv run alembic upgrade head` against dev DB; verify cleanly applies. `uv run pytest packages/db/tests/test_migration_m4.py -x` green.
- [ ] **0.5** Add SQLAlchemy ORM models:
  - `packages/db/suitest_db/models/eval_run.py` — `EvalRun` class with all columns mapped + relationship to `Workspace`.
  - `packages/db/suitest_db/models/eval_fixture.py` — `EvalFixture` class.
  - `packages/db/suitest_db/models/cost_aggregate.py` — `CostAggregate` class with composite unique index declared via `__table_args__`.
  - `packages/db/suitest_db/models/i18n_preference.py` — `I18nPreference` class.
  - `packages/db/suitest_db/models/budget_config.py` — `BudgetConfig` class.
- [ ] **0.6** Repository classes under `packages/db/suitest_db/repositories/`:
  - `eval_run_repo.py` — methods: `create`, `get_by_id`, `list_by_workspace`, `update_status`, `complete`, `latest_for_suite`.
  - `eval_fixture_repo.py` — `create`, `get_by_name`, `list_by_kind`, `bulk_upsert`.
  - `cost_aggregate_repo.py` — `upsert_daily`, `query_range`, `top_providers`, `total_for_workspace`.
  - `i18n_preference_repo.py` — `get_or_default`, `upsert`.
  - `budget_config_repo.py` — `get_or_default`, `upsert`, `check_threshold`.
- [ ] **0.7** Repository unit tests under `packages/db/tests/test_repos_m4.py`. Cover happy + cross-workspace 404 + upsert idempotency.
- [ ] **0.8** Commit: `feat(db): add eval_runs, eval_fixtures, cost_aggregates, i18n_preferences, budget_configs (Closes #M4-8 #M4-9 #M4-12)`.

---

## Task 1: LOCAL tier — Ollama backend wiring

Validate the Ollama backend end-to-end in dev compose, with LiteLLM routing and integration tests.

### 1.1 Compose profile for LOCAL tier with Ollama

- [ ] **1.1.1** Edit `docker-compose.yml` to confirm `ollama` service block (added in `docs/DEPLOYMENT.md` §1.2) — image `ollama/ollama:0.4.0` (pinned), `profiles: ["local"]`, volume `ollamadata:/root/.ollama`, port `11434:11434`, healthcheck `curl -f http://localhost:11434/api/tags`.
- [ ] **1.1.2** Add `ollama-init` service (one-shot job, `profiles: ["local"]`) that runs `ollama pull llama3.1:8b-instruct` on first boot. `depends_on: ollama: { condition: service_healthy }`. `restart: "no"`. Image: same `ollama/ollama:0.4.0`.
- [ ] **1.1.3** Update `.env.example` LOCAL tier section to document:
  ```env
  # LOCAL tier (Ollama)
  # docker compose --profile local up -d
  SUITEST_LLM_PROVIDER=ollama
  SUITEST_LLM_BASE_URL=http://ollama:11434
  SUITEST_LLM_MODEL=ollama/llama3.1:8b-instruct
  SUITEST_EMBEDDINGS_BACKEND=fastembed
  ```

### 1.2 LiteLLM Ollama provider config

- [ ] **1.2.1** Edit `packages/agent/src/suitest_agent/providers/litellm_router.py` (from M3) — verify `_PROVIDER_TO_PREFIX` includes `ollama → "ollama/"`. Add `_PROVIDER_BASE_URL_OVERRIDE` map for LOCAL providers:
  ```python
  _PROVIDER_BASE_URL_OVERRIDE: Final[dict[str, str | None]] = {
      "ollama": None,         # set from SUITEST_LLM_BASE_URL
      "llamacpp": None,
      "vllm": None,
      "lmstudio": None,
  }
  ```
- [ ] **1.2.2** In `build_router()` function, if provider in LOCAL_PROVIDERS and `SUITEST_LLM_BASE_URL` is set, pass `api_base=base_url` to LiteLLM's `completion()`. Add `litellm.api_base` global only inside the router instance, never module-global.
- [ ] **1.2.3** Add `_OLLAMA_REQUEST_TIMEOUT_S = 120` (LOCAL inference is slower than CLOUD). Configurable via `SUITEST_LLM_REQUEST_TIMEOUT_S`.

### 1.3 Pytest integration test — Ollama

- [ ] **1.3.1** Create `packages/agent/tests/test_local_ollama.py`:
  ```python
  import pytest
  from testcontainers.core.container import DockerContainer
  from testcontainers.core.waiting_utils import wait_for_logs
  from suitest_agent.providers.litellm_router import build_router

  @pytest.fixture(scope="module")
  def ollama_container():
      c = DockerContainer("ollama/ollama:0.4.0").with_exposed_ports(11434)
      c.start()
      try:
          wait_for_logs(c, "Listening on", timeout=60)
          host = c.get_container_host_ip()
          port = c.get_exposed_port(11434)
          # pull tiny model qwen2.5:0.5b for CI speed (~350MB)
          import subprocess
          subprocess.run(["docker", "exec", c._container.id, "ollama", "pull", "qwen2.5:0.5b"], check=True)
          yield f"http://{host}:{port}"
      finally:
          c.stop()

  @pytest.mark.integration
  @pytest.mark.slow
  async def test_ollama_generation_smoke(ollama_container, monkeypatch):
      monkeypatch.setenv("SUITEST_LLM_PROVIDER", "ollama")
      monkeypatch.setenv("SUITEST_LLM_BASE_URL", ollama_container)
      monkeypatch.setenv("SUITEST_LLM_MODEL", "ollama/qwen2.5:0.5b")
      router = build_router()
      response = await router.acompletion(
          messages=[{"role": "user", "content": "Reply with the single word: OK"}],
          temperature=0.0,
          max_tokens=10,
      )
      assert response.choices[0].message.content is not None
      # LLM non-deterministic — assert structure not exact text
      assert len(response.choices[0].message.content) > 0
  ```
- [ ] **1.3.2** Mark test as `@pytest.mark.integration @pytest.mark.slow` — excluded from default `pytest`, included in CI nightly job.
- [ ] **1.3.3** Add `pytest.ini` markers if not present: `integration: slow tests against real services`, `slow: tests that take >10s`.

### 1.4 Generation harness against Ollama — structural assertion

- [ ] **1.4.1** Create `packages/agent/tests/test_local_ollama_generation.py`:
  ```python
  @pytest.mark.integration
  @pytest.mark.slow
  async def test_ollama_prd_generates_structured_cases(ollama_container, monkeypatch, generation_graph):
      """Smoke: PRD generation against ollama returns >=1 case with required fields."""
      monkeypatch.setenv("SUITEST_LLM_PROVIDER", "ollama")
      monkeypatch.setenv("SUITEST_LLM_BASE_URL", ollama_container)
      monkeypatch.setenv("SUITEST_LLM_MODEL", "ollama/qwen2.5:0.5b")
      prd = "As a user I can log in with email and password. Invalid credentials show an error."
      result = await generation_graph.ainvoke({"source": "prd", "input": prd, "workspace_id": "ws_test"})
      cases = result["cases"]
      assert isinstance(cases, list)
      assert len(cases) >= 1
      for case in cases:
          assert "title" in case
          assert "steps" in case
          assert isinstance(case["steps"], list)
  ```
- [ ] **1.4.2** Tolerance: small LLM may produce sparse output. Assert structure presence not content quality. Quality is eval harness scope (Task 13).

### 1.5 Manual smoke checklist

- [ ] **1.5.1** Document under `docs/RUNBOOK.md` (created in Task 27) — section "LOCAL tier smoke":
  ```
  1. `docker compose --profile local up -d`
  2. Wait for `ollama-init` to complete (model pulled).
  3. Edit `.env`: set SUITEST_LLM_PROVIDER=ollama, base_url, model.
  4. `docker compose restart api runner`
  5. Open localhost:8080 → Settings → LLM → Test connection → expect green.
  6. Dashboard → AI panel visible. Tier badge shows `LOCAL · ollama:llama3.1:8b-instruct`.
  7. Create case via "Generate from PRD" → expect cases drafted.
  ```

### 1.6 CI gate

- [ ] **1.6.1** Add GitHub Actions workflow `.github/workflows/local-tier-smoke.yml`:
  - Runs nightly + on PR label `test:local`.
  - Spins up docker-compose with `--profile local`.
  - Runs `uv run pytest -m integration packages/agent/tests/test_local_ollama.py packages/agent/tests/test_local_ollama_generation.py -x`.
  - Uploads logs on failure.

- [ ] **1.7** Commit: `feat(local): wire ollama backend with integration tests (Closes #M4-1)`.

---

## Task 2: LOCAL tier — llamacpp + vLLM + LM Studio

Each subbacked has its own quirks. Validate all three.

### 2.1 llama.cpp server

- [ ] **2.1.1** Document llama.cpp server in `docs/DEPLOYMENT.md` §1.7 (new section) — recommended run command:
  ```bash
  docker run --rm -p 8080:8080 ghcr.io/ggerganov/llama.cpp:server \
    --host 0.0.0.0 --port 8080 --hf-repo bartowski/Qwen2.5-0.5B-Instruct-GGUF --hf-file qwen2.5-0.5b-instruct-q4_k_m.gguf
  ```
- [ ] **2.1.2** Edit `_PROVIDER_BASE_URL_OVERRIDE` so `llamacpp` maps via LiteLLM `openai/`-prefixed routing (llama.cpp exposes OpenAI-compatible endpoint at `/v1`). Verify `packages/agent/src/suitest_agent/providers/litellm_router.py` builds model_string as `openai/<model>` with `api_base=http://llamacpp:8080/v1` and dummy `api_key="sk-local"`.
- [ ] **2.1.3** Pytest `packages/agent/tests/test_local_llamacpp.py` — uses `testcontainers` with `ghcr.io/ggerganov/llama.cpp:server-b3500` (pinned tag), pulls GGUF model from HF on container start. Skip if `HF_TOKEN` not set or `CI_FULL=1` not set (HF download is slow).
- [ ] **2.1.4** Alternative: lighter-weight test using **mock OpenAI-compatible endpoint** (`pytest-httpserver`) — proves LiteLLM correctly routes to `base_url` regardless of backend identity. Test always runs:
  ```python
  async def test_llamacpp_routing_via_mock_openai(monkeypatch, httpserver):
      httpserver.expect_request("/v1/chat/completions").respond_with_json({
          "id": "chatcmpl-mock", "choices": [{"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop", "index": 0}],
          "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}, "model": "qwen2.5-0.5b"
      })
      monkeypatch.setenv("SUITEST_LLM_PROVIDER", "llamacpp")
      monkeypatch.setenv("SUITEST_LLM_BASE_URL", httpserver.url_for("/v1"))
      monkeypatch.setenv("SUITEST_LLM_MODEL", "qwen2.5-0.5b")
      router = build_router()
      response = await router.acompletion(messages=[{"role": "user", "content": "ping"}])
      assert response.choices[0].message.content == "OK"
  ```
- [ ] **2.1.5** Commit: `feat(local): wire llamacpp backend (Closes #M4-1)`.

### 2.2 vLLM server

- [ ] **2.2.1** Document vLLM in `docs/DEPLOYMENT.md` §1.7 — `vllm serve Qwen/Qwen2.5-0.5B-Instruct --port 8000`. Note GPU is recommended; CPU mode possible but slow.
- [ ] **2.2.2** Provider mapping: `vllm` → OpenAI-compatible at `http://vllm:8000/v1`. Same `openai/<model>` routing as llamacpp.
- [ ] **2.2.3** Mock-based test `packages/agent/tests/test_local_vllm.py` — same pattern as llamacpp. Real-service test gated by `VLLM_TEST_URL` env (developer/CI runs it manually with running vLLM instance).
- [ ] **2.2.4** Document supported model formats in `docs/CAPABILITY_TIERS.md` §3 footnote: vLLM = HF-style safetensors / GGUF (via `vllm` GGUF support); llama.cpp = GGUF only; Ollama = Ollama Modelfile format (built-in pulls); LM Studio = GGUF + MLX.
- [ ] **2.2.5** Commit: `feat(local): wire vllm backend (Closes #M4-1)`.

### 2.3 LM Studio server

- [ ] **2.3.1** Document LM Studio in `docs/DEPLOYMENT.md` §1.7 — desktop-app launches OpenAI-compatible server at `http://localhost:1234/v1`. Note: LM Studio is desktop-only; not containerizable. Self-host use case: dev laptop pointing api at host.docker.internal:1234.
- [ ] **2.3.2** Provider mapping: `lmstudio` → `http://lmstudio:1234/v1` (or `http://host.docker.internal:1234/v1` for laptop dev).
- [ ] **2.3.3** Mock-based test `packages/agent/tests/test_local_lmstudio.py` — pattern identical to vLLM/llamacpp.
- [ ] **2.3.4** Add support matrix to `docs/CAPABILITY_TIERS.md` §2 footnote — table of LOCAL backends with: container-friendly?, GPU recommended?, model formats, recommended models for QA-sized hardware.
- [ ] **2.3.5** Commit: `feat(local): wire lmstudio backend (Closes #M4-1)`.

### 2.4 LOCAL tier provider parity matrix in `/capabilities`

- [ ] **2.4.1** Edit `apps/api/src/suitest_api/routers/capabilities.py` to populate `llm.base_url` from env when tier=LOCAL. Add `llm.supports_streaming` boolean (Ollama YES, llamacpp YES, vllm YES, lmstudio YES — all OpenAI-compatible) and `llm.supports_tools` boolean (Ollama partial, others depends on model — set conservative `false` unless `SUITEST_LLM_SUPPORTS_TOOLS=1`).
- [ ] **2.4.2** UI: `apps/web/src/components/shell/TierBadge.tsx` already renders `LOCAL · ollama:llama3.1`. Verify all 4 backends render correctly (`LOCAL · llamacpp:qwen2.5-0.5b`, `LOCAL · vllm:qwen2.5-0.5b`, `LOCAL · lmstudio:qwen2.5-0.5b`).
- [ ] **2.4.3** Vitest snapshot `apps/web/src/components/shell/__tests__/TierBadge.local.test.tsx` covers all 4 LOCAL providers.
- [ ] **2.4.4** Commit: `feat(api): expose local backend metadata in /capabilities (Closes #M4-1)`.

---

## Task 3: `fastembed` local embeddings backend

Add the in-process CPU embeddings backend so ZERO+fastembed = free semantic search.

### 3.1 Dependency add + lazy import

- [ ] **3.1.1** Edit `packages/agent/pyproject.toml` — add `[project.optional-dependencies]` group:
  ```toml
  embeddings-local = ["fastembed>=0.4.0,<0.5"]
  ```
- [ ] **3.1.2** Document install: `uv pip install --group embeddings-local` (default ZERO-tier install excludes it; opt-in for ZERO+fastembed). For Docker images, `Dockerfile.api` always installs the group because the model is only loaded if `SUITEST_EMBEDDINGS_BACKEND=fastembed`.
- [ ] **3.1.3** Add `fastembed` to `apps/api/Dockerfile` build stage as conditional `RUN if [ "$INCLUDE_EMBEDDINGS_LOCAL" = "1" ]; then uv pip install --group embeddings-local; fi`. Set `INCLUDE_EMBEDDINGS_LOCAL=1` in default image build for ZERO+fastembed combo readiness; can be unset for ultra-minimal builds.

### 3.2 Backend dispatcher

- [ ] **3.2.1** Edit `packages/agent/src/suitest_agent/rag/embeddings.py` (created in M3) — confirm dispatcher signature:
  ```python
  from __future__ import annotations
  from typing import Protocol
  from suitest_core.capabilities import EmbeddingsConfig

  class EmbeddingsBackend(Protocol):
      dim: int
      model_name: str
      async def embed(self, texts: list[str]) -> list[list[float]]: ...
      async def embed_query(self, text: str) -> list[float]: ...
  ```
- [ ] **3.2.2** Add `class FastembedBackend(EmbeddingsBackend)`:
  ```python
  class FastembedBackend:
      dim: int = 384
      model_name: str = "BAAI/bge-small-en-v1.5"
      def __init__(self, model_name: str | None = None) -> None:
          self.model_name = model_name or self.model_name
          self._model = None  # lazy-loaded
          self._lock = asyncio.Lock()

      async def _ensure_loaded(self) -> None:
          if self._model is not None:
              return
          async with self._lock:
              if self._model is not None:
                  return
              # fastembed is sync; offload to thread
              from fastembed import TextEmbedding
              loop = asyncio.get_running_loop()
              self._model = await loop.run_in_executor(None, lambda: TextEmbedding(self.model_name))

      async def embed(self, texts: list[str]) -> list[list[float]]:
          await self._ensure_loaded()
          assert self._model is not None
          loop = asyncio.get_running_loop()
          # fastembed returns generator; convert in thread
          return await loop.run_in_executor(None, lambda: [list(v) for v in self._model.embed(texts)])

      async def embed_query(self, text: str) -> list[float]:
          # bge-small uses same encoder for query+passage; no prefix dance needed
          (vec,) = await self.embed([text])
          return vec
  ```
- [ ] **3.2.3** Wire dispatcher `get_backend(cfg: EmbeddingsConfig) -> EmbeddingsBackend`:
  ```python
  def get_backend(cfg: EmbeddingsConfig) -> EmbeddingsBackend:
      if not cfg.enabled:
          raise EmbeddingsDisabledError("EMBEDDINGS_DISABLED")
      if cfg.backend == "fastembed":
          return FastembedBackend(cfg.model)
      if cfg.backend == "openai":
          return OpenAIBackend(cfg.model)        # from M3
      if cfg.backend == "cohere":
          return CohereBackend(cfg.model)        # from M3
      raise ValueError(f"Unknown backend: {cfg.backend}")
  ```
- [ ] **3.2.4** Singleton in `packages/agent/src/suitest_agent/rag/embeddings_singleton.py` — `get_embeddings() -> EmbeddingsBackend` cached on first call, respects `EmbeddingsConfig` resolved at startup.

### 3.3 Lazy warmup on app start

- [ ] **3.3.1** Edit `apps/api/src/suitest_api/main.py` lifespan — if `embeddings.enabled` and `backend == "fastembed"`, schedule background task:
  ```python
  @asynccontextmanager
  async def lifespan(app: FastAPI):
      # ... existing startup ...
      if settings.embeddings.enabled and settings.embeddings.backend == "fastembed":
          asyncio.create_task(_warmup_embeddings())
      yield
      # ... existing shutdown ...

  async def _warmup_embeddings() -> None:
      try:
          backend = get_embeddings()
          await backend.embed_query("warmup")
          log.info("fastembed_warmup_complete", model=backend.model_name, dim=backend.dim)
      except Exception as e:
          log.warning("fastembed_warmup_failed", error=str(e))
  ```
- [ ] **3.3.2** First user-facing query waits if warmup not done (no busy-wait — backend's own lock handles serialization).

### 3.4 pgvector dim check

- [ ] **3.4.1** Alembic migration check: `packages/db/suitest_db/migrations/env.py` — on startup compare `document_chunk.embedding` Vector dim against `EmbeddingsConfig.dim`. If mismatch, log WARN and refuse to start with `ConfigError("EMBEDDINGS_DIM_MISMATCH: column=<X>, backend=<Y>")`. Backend switch requires re-embed (Task 4).
- [ ] **3.4.2** Pytest `packages/db/tests/test_embeddings_dim_check.py`:
  - With backend=fastembed (384) and column=Vector(384) → OK.
  - With backend=openai (1536) and column=Vector(384) → ConfigError raised.

### 3.5 Tests

- [ ] **3.5.1** Pytest `packages/agent/tests/test_fastembed_backend.py`:
  - Mock fastembed (no real model load in default CI to keep tests fast) via `monkeypatch.setattr("fastembed.TextEmbedding", FakeEmbedding)`.
  - Real-model test marked `@pytest.mark.slow` — actually loads BAAI/bge-small (~130MB), verifies `vec = await backend.embed_query("hello world")` returns 384-dim list of floats summing to non-zero.
- [ ] **3.5.2** Semantic similarity smoke:
  ```python
  @pytest.mark.slow
  async def test_fastembed_similarity_smoke():
      backend = FastembedBackend()
      vecs = await backend.embed(["the cat sat on the mat", "feline rests on rug", "deploy to kubernetes"])
      import numpy as np
      a, b, c = np.array(vecs[0]), np.array(vecs[1]), np.array(vecs[2])
      sim_ab = (a @ b) / (np.linalg.norm(a) * np.linalg.norm(b))
      sim_ac = (a @ c) / (np.linalg.norm(a) * np.linalg.norm(c))
      assert sim_ab > sim_ac  # semantically related closer than unrelated
  ```
- [ ] **3.5.3** Integration test via `GET /search?semantic=1` end-to-end in `apps/api/tests/test_search_semantic_fastembed.py` — workspace has 5 cases, embeddings re-built on fastembed backend, query "login flow" returns case with that title in top-3.

- [ ] **3.6** Commit: `feat(rag): fastembed local embeddings backend (Closes #M4-2)`.

---

## Task 4: Embeddings backend matrix + re-embed migration helper

When backend changes (e.g., ZERO+none → ZERO+fastembed), existing chunks must be re-embedded.

### 4.1 Document the matrix

- [ ] **4.1.1** Update `docs/CAPABILITY_TIERS.md` §5 — confirm matrix already includes all combos. Add explicit recommendation column:
  - ZERO + `fastembed` → **Recommended for air-gap with semantic search**
  - ZERO + `none` → FTS-only, lightest deployment
  - CLOUD + `openai` → Best semantic quality, paid
  - LOCAL + `fastembed` → **Recommended for air-gap with full AI**

### 4.2 Re-embed admin tool

- [ ] **4.2.1** Create `packages/db/suitest_db/scripts/reembed.py`:
  ```python
  """Re-embed all document_chunks for a workspace with the currently-configured backend.

  Usage:
      uv run python -m packages.db.suitest_db.scripts.reembed --workspace <id> [--batch 64]

  Idempotent: only re-embeds chunks whose stored vector dim != current backend dim,
  OR chunks with embedding=NULL.
  """
  from __future__ import annotations
  import argparse, asyncio, logging
  from suitest_agent.rag.embeddings import get_embeddings
  from suitest_db.repositories.document_chunk_repo import DocumentChunkRepo
  from suitest_db.session import async_session_factory

  log = logging.getLogger(__name__)

  async def reembed_workspace(workspace_id: str, batch: int = 64) -> int:
      backend = get_embeddings()
      total = 0
      async with async_session_factory() as session:
          repo = DocumentChunkRepo(session)
          while True:
              chunks = await repo.list_chunks_needing_reembed(workspace_id, dim=backend.dim, limit=batch)
              if not chunks:
                  break
              vecs = await backend.embed([c.text for c in chunks])
              await repo.bulk_update_embeddings([(c.id, v) for c, v in zip(chunks, vecs)])
              await session.commit()
              total += len(chunks)
              log.info("reembed_batch", workspace=workspace_id, count=len(chunks), total=total)
      return total

  if __name__ == "__main__":
      p = argparse.ArgumentParser()
      p.add_argument("--workspace", required=True)
      p.add_argument("--batch", type=int, default=64)
      args = p.parse_args()
      n = asyncio.run(reembed_workspace(args.workspace, args.batch))
      print(f"re-embedded {n} chunks")
  ```
- [ ] **4.2.2** Add repo method `DocumentChunkRepo.list_chunks_needing_reembed(workspace_id, dim, limit)` — returns rows where `vector_dim(embedding) != dim OR embedding IS NULL`. Use `vector_dims()` pgvector function or store `embedding_dim` column.
- [ ] **4.2.3** Decision: simpler approach — add column `document_chunks.embedding_backend text NULL, embedding_dim int NULL` in Task 0 migration. Reembed = `WHERE workspace_id = $1 AND (embedding_backend IS NULL OR embedding_backend != $2)`. Update Task 0 migration to include these columns; add column-rename downgrade.
- [ ] **4.2.4** API endpoint `POST /admin/reembed` (gated to ADMIN+, returns job id) enqueues ARQ job. Read job status via `GET /admin/jobs/:id`. Background-only — never block API request thread.

### 4.3 ARQ job

- [ ] **4.3.1** Create `apps/runner/src/suitest_runner/jobs/reembed_workspace.py`:
  ```python
  from arq import ArqRedis
  from suitest_db.suitest_db.scripts.reembed import reembed_workspace

  async def reembed_workspace_job(ctx: dict, workspace_id: str, batch: int = 64) -> dict[str, int]:
      n = await reembed_workspace(workspace_id, batch)
      return {"reembedded": n}
  ```
- [ ] **4.3.2** Register in `apps/runner/src/suitest_runner/worker.py` `functions` list.

### 4.4 Tests

- [ ] **4.4.1** Pytest `packages/db/tests/test_reembed.py`:
  - Seed 10 chunks with `embedding_backend='none'`, embedding NULL.
  - Switch to fastembed (mock backend dim=384 returning constant vector).
  - Run `reembed_workspace("ws_test")` → returns 10.
  - Verify all rows have `embedding_backend='fastembed'`, `embedding_dim=384`, embedding != NULL.
  - Run again (idempotent) → returns 0.
  - Switch to backend dim=1536 → re-embeds all 10 again.

- [ ] **4.5** Commit: `feat(rag): re-embed helper + backend metadata columns (Closes #M4-2)`.

---

## Task 5: FTS fallback for ZERO + `embeddings=none`

When embeddings disabled, search must still work via Postgres `tsvector`.

### 5.1 tsvector column

- [ ] **5.1.1** Add to Task 0 migration: `document_chunks.search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(text, ''))) STORED`. Index `ix_document_chunks_search_tsv` USING GIN (search_tsv).
- [ ] **5.1.2** Also add tsvector to `test_cases`: `test_cases.search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(title, '') || ' ' || coalesce(description, ''))) STORED` + GIN index.

### 5.2 Retriever dispatcher

- [ ] **5.2.1** Edit `packages/agent/src/suitest_agent/rag/retriever.py` (from M3):
  ```python
  class Retriever:
      def __init__(self, backend_config: EmbeddingsConfig, repo: DocumentChunkRepo, fts_repo: FtsRepo):
          self.cfg = backend_config
          self.repo = repo
          self.fts_repo = fts_repo

      async def search(self, workspace_id: str, query: str, k: int = 5) -> list[Chunk]:
          if self.cfg.enabled:
              backend = get_embeddings()
              qvec = await backend.embed_query(query)
              return await self.repo.semantic_search(workspace_id, qvec, k)
          return await self.fts_repo.fts_search(workspace_id, query, k)
  ```
- [ ] **5.2.2** Repository `FtsRepo.fts_search(workspace_id, query, k)`:
  ```sql
  SELECT id, text, doc_id,
         ts_rank(search_tsv, websearch_to_tsquery('english', :query)) AS rank
  FROM document_chunks
  WHERE workspace_id = :workspace_id
    AND search_tsv @@ websearch_to_tsquery('english', :query)
  ORDER BY rank DESC
  LIMIT :k
  ```
- [ ] **5.2.3** Add `GET /api/v1/search?q=<query>&semantic=<0|1>` — controller selects strategy:
  - `semantic=1` + embeddings disabled → `409 EMBEDDINGS_DISABLED`
  - `semantic=1` + embeddings enabled → semantic search
  - `semantic=0` (or default) → FTS

### 5.3 Tests

- [ ] **5.3.1** Pytest `apps/api/tests/test_search_fts.py`:
  - Seed cases: "User login flow", "Checkout E2E test", "Payment processing".
  - GET /search?q=login → returns "User login flow" first.
  - GET /search?q=login&semantic=1 with embeddings=none → 409.
- [ ] **5.3.2** Pytest `apps/api/tests/test_search_semantic.py` (depends on Task 3):
  - Same seed, embeddings=fastembed (mock fixed vectors).
  - GET /search?q=login&semantic=1 → returns "User login flow" in top-3.

- [ ] **5.4** Commit: `feat(rag): FTS fallback + search dispatcher (Closes #M4-2)`.

---

## Task 6: Helm chart — production-grade base templates

Promote `infra/helm/suitest/` skeleton from M0 to production-grade.

### 6.1 Chart skeleton verification

- [ ] **6.1.1** Verify `infra/helm/suitest/Chart.yaml` — bump version to `1.0.0`, set `appVersion: "1.0.0"`, declare subchart dependencies (bitnami/postgresql, bitnami/redis, bitnami/minio, optional langfuse). Example:
  ```yaml
  apiVersion: v2
  name: suitest
  description: MCP-native testing platform (manual TCM + deterministic + AI when configured)
  type: application
  version: 1.0.0
  appVersion: "1.0.0"
  home: https://suitest.dev
  sources:
    - https://github.com/suitest-dev/suitest
  maintainers:
    - name: Suitest Maintainers
      email: maintainers@suitest.dev
  keywords: [testing, qa, tcm, mcp, e2e]
  dependencies:
    - name: postgresql
      version: "15.5.x"
      repository: oci://registry-1.docker.io/bitnamicharts
      condition: postgres.embedded
    - name: redis
      version: "19.6.x"
      repository: oci://registry-1.docker.io/bitnamicharts
      condition: redis.embedded
    - name: minio
      version: "14.6.x"
      repository: oci://registry-1.docker.io/bitnamicharts
      condition: s3.embedded
  ```
- [ ] **6.1.2** Run `helm dependency update infra/helm/suitest/` → vendor charts into `charts/` subdir. Commit lockfile `Chart.lock`.

### 6.2 `values.yaml` — full schema with sane defaults

- [ ] **6.2.1** Edit `infra/helm/suitest/values.yaml` to match `docs/DEPLOYMENT.md` §3.2 exactly. Add inline comments above each key. Required additional keys not yet in M0 skeleton:
  - `keda.enabled: false` (default off; opt-in for autoscale-by-queue)
  - `keda.scaledObject.queueDepthThreshold: 10`
  - `certManager.enabled: false` + `certManager.clusterIssuer: "letsencrypt-prod"`
  - `serviceMonitor.enabled: false` + `serviceMonitor.interval: "30s"` + `serviceMonitor.namespace: ""` (use release ns by default)
  - `networkPolicy.defaultDeny: true` (new in M4 — M0 had a placeholder)
  - `networkPolicy.egress.allowDns: true` (always-on for service discovery)
  - `networkPolicy.egress.allowLLMHosts: []` (FQDN list for CLOUD egress)
  - `mcp.bundledImage: ghcr.io/suitest-dev/mcp-bundle:1.0.0` (sidecar with all bundled MCP binaries; air-gap-friendly)
  - `langfuse.enabled: false` (optional subchart toggle)

### 6.3 Templates — Deployment + Service per app

- [ ] **6.3.1** `templates/api-deployment.yaml` — full Deployment with:
  - 3 replicas default, rolling update strategy (maxSurge=25%, maxUnavailable=0)
  - container image from `.Values.image.registry`/`api:.Values.suitest.version`
  - env from ConfigMap + Secret + LLM apiKeySecretRef
  - resources requests/limits from `.Values.api.resources`
  - probes: liveness `/health`, readiness `/ready` (DB+Redis+S3 check), startup `/health` with 60s graceperiod
  - securityContext: runAsNonRoot=true, readOnlyRootFilesystem=true, allowPrivilegeEscalation=false, capabilities.drop=[ALL]
  - serviceAccountName from `templates/serviceaccount.yaml`
  - topologySpreadConstraints across hostname for HA
- [ ] **6.3.2** `templates/api-service.yaml` — ClusterIP service exposing 8000, with prometheus scrape annotations:
  ```yaml
  metadata:
    annotations:
      prometheus.io/scrape: "true"
      prometheus.io/path: "/metrics"
      prometheus.io/port: "8000"
  ```
- [ ] **6.3.3** `templates/runner-deployment.yaml` — similar shape, 2 replicas default, no service (runner is queue-pulled), env injects `SUITEST_RUNNER_ROLE=runner`, longer terminationGracePeriodSeconds=90 (drain in-flight jobs).
- [ ] **6.3.4** `templates/web-deployment.yaml` — 2 replicas, nginx serving SPA, lighter resources (`50m/64Mi` req).
- [ ] **6.3.5** `templates/web-service.yaml` + `templates/web-ingress.yaml` — Ingress with cert-manager annotation when `.Values.certManager.enabled`.

### 6.4 PodDisruptionBudget

- [ ] **6.4.1** `templates/api-pdb.yaml`:
  ```yaml
  {{- if gt (.Values.api.replicaCount | int) 1 }}
  apiVersion: policy/v1
  kind: PodDisruptionBudget
  metadata:
    name: {{ include "suitest.fullname" . }}-api
    labels: {{- include "suitest.labels" . | nindent 4 }}
  spec:
    minAvailable: {{ .Values.api.podDisruptionBudget.minAvailable | default 1 }}
    selector:
      matchLabels:
        {{- include "suitest.selectorLabels" . | nindent 6 }}
        app.kubernetes.io/component: api
  {{- end }}
  ```
- [ ] **6.4.2** Same pattern for `runner-pdb.yaml` and `web-pdb.yaml`.

### 6.5 HPA basic (cpu/mem)

- [ ] **6.5.1** `templates/api-hpa.yaml`:
  ```yaml
  {{- if .Values.api.hpa.enabled }}
  apiVersion: autoscaling/v2
  kind: HorizontalPodAutoscaler
  metadata:
    name: {{ include "suitest.fullname" . }}-api
  spec:
    scaleTargetRef:
      apiVersion: apps/v1
      kind: Deployment
      name: {{ include "suitest.fullname" . }}-api
    minReplicas: {{ .Values.api.hpa.minReplicas }}
    maxReplicas: {{ .Values.api.hpa.maxReplicas }}
    metrics:
      - type: Resource
        resource:
          name: cpu
          target:
            type: Utilization
            averageUtilization: {{ .Values.api.hpa.targetCPUUtilizationPercentage }}
    behavior:
      scaleDown:
        stabilizationWindowSeconds: 300
      scaleUp:
        stabilizationWindowSeconds: 30
  {{- end }}
  ```
- [ ] **6.5.2** Same pattern for `web-hpa.yaml`. Runner HPA → KEDA (Task 7).

### 6.6 ServiceMonitor for Prometheus

- [ ] **6.6.1** `templates/servicemonitor.yaml`:
  ```yaml
  {{- if and .Values.serviceMonitor.enabled (.Capabilities.APIVersions.Has "monitoring.coreos.com/v1") }}
  apiVersion: monitoring.coreos.com/v1
  kind: ServiceMonitor
  metadata:
    name: {{ include "suitest.fullname" . }}
    {{- if .Values.serviceMonitor.namespace }}
    namespace: {{ .Values.serviceMonitor.namespace }}
    {{- end }}
    labels: {{- include "suitest.labels" . | nindent 4 }}
  spec:
    selector:
      matchLabels:
        {{- include "suitest.selectorLabels" . | nindent 8 }}
        app.kubernetes.io/component: api
    endpoints:
      - port: http
        path: /metrics
        interval: {{ .Values.serviceMonitor.interval | default "30s" }}
  {{- end }}
  ```

### 6.7 ConfigMap + Secret

- [ ] **6.7.1** `templates/configmap.yaml` — all non-secret env (LLM provider name, model id, base URL, embeddings backend, tier, autonomy default, S3 endpoint, S3 bucket).
- [ ] **6.7.2** `templates/secret.yaml` — generates `suitest-secrets` Secret stub if not externally provided:
  ```yaml
  apiVersion: v1
  kind: Secret
  metadata:
    name: {{ include "suitest.fullname" . }}-secrets
  type: Opaque
  data:
    auth-secret: {{ randAlphaNum 32 | b64enc | quote }}
    encryption-key: {{ randBytes 32 | b64enc | quote }}
    {{- if .Values.llm.apiKey }}
    llm-api-key: {{ .Values.llm.apiKey | b64enc | quote }}
    {{- end }}
  ```
  Note: `randAlphaNum`/`randBytes` only run on first install (deterministic with `--reuse-values`). Production users should pre-create the Secret and set `existingSecretRef`.
- [ ] **6.7.3** Add `.Values.existingSecretRef` override path; templates conditionally skip secret generation when reference provided.

### 6.8 Migration Job

- [ ] **6.8.1** `templates/migration-job.yaml` — pre-install + pre-upgrade Helm hook:
  ```yaml
  apiVersion: batch/v1
  kind: Job
  metadata:
    name: {{ include "suitest.fullname" . }}-migrate-{{ .Release.Revision }}
    annotations:
      "helm.sh/hook": pre-install,pre-upgrade
      "helm.sh/hook-weight": "-5"
      "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
  spec:
    backoffLimit: 3
    template:
      spec:
        restartPolicy: Never
        containers:
          - name: alembic
            image: "{{ .Values.image.registry }}/suitest-api:{{ .Values.suitest.version }}"
            command: ["uv", "run", "alembic", "upgrade", "head"]
            envFrom:
              - configMapRef: { name: {{ include "suitest.fullname" . }}-config }
              - secretRef: { name: {{ default (printf "%s-secrets" (include "suitest.fullname" .)) .Values.existingSecretRef }} }
  ```

### 6.9 Tests

- [ ] **6.9.1** Add `tests/unit/helm_lint_test.sh`:
  ```bash
  #!/usr/bin/env bash
  set -euo pipefail
  cd infra/helm/suitest
  helm dependency update
  helm lint .
  helm template suitest . --values values.yaml > /tmp/render-zero.yaml
  helm template suitest . --values values-cloud.yaml > /tmp/render-cloud.yaml
  helm template suitest . --values values-local.yaml > /tmp/render-local.yaml
  kubeconform -strict -summary -schema-location default -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' /tmp/render-zero.yaml /tmp/render-cloud.yaml /tmp/render-local.yaml
  ```
- [ ] **6.9.2** GitHub Actions step in `.github/workflows/ci.yml`:
  ```yaml
  - name: Helm lint + template
    run: bash tests/unit/helm_lint_test.sh
  ```
- [ ] **6.9.3** Each template task (Deployments, HPA, PDB, Service, Ingress, NetworkPolicy, ConfigMap, Secret, Job, ServiceMonitor) must pass `helm template`, `helm lint`, and `kubeconform -strict`.

- [ ] **6.10** Commit: `feat(helm): production-grade base templates with probes/PDB/HPA (Closes #M4-3)`.

---

## Task 7: HPA via KEDA — runner queue-depth scaling

KEDA-based autoscaling for runner based on Redis queue depth (ARQ default).

### 7.1 KEDA installation requirement

- [ ] **7.1.1** Document in `docs/DEPLOYMENT.md` §3.4 — KEDA is an external prerequisite. Install via `helm install keda kedacore/keda --namespace keda --create-namespace`. Suitest chart references KEDA CRDs but does not install KEDA itself.
- [ ] **7.1.2** Add `tools/check-keda-installed.sh` — `kubectl get crd scaledobjects.keda.sh` returns 0 if installed.

### 7.2 ScaledObject template

- [ ] **7.2.1** Create `templates/runner-scaledobject.yaml`:
  ```yaml
  {{- if and .Values.keda.enabled (.Capabilities.APIVersions.Has "keda.sh/v1alpha1") }}
  apiVersion: keda.sh/v1alpha1
  kind: ScaledObject
  metadata:
    name: {{ include "suitest.fullname" . }}-runner
    labels: {{- include "suitest.labels" . | nindent 4 }}
  spec:
    scaleTargetRef:
      apiVersion: apps/v1
      kind: Deployment
      name: {{ include "suitest.fullname" . }}-runner
    pollingInterval: {{ .Values.keda.pollingInterval | default 15 }}
    cooldownPeriod: {{ .Values.keda.cooldownPeriod | default 60 }}
    idleReplicaCount: 0
    minReplicaCount: {{ .Values.runner.hpa.minReplicas }}
    maxReplicaCount: {{ .Values.runner.hpa.maxReplicas }}
    fallback:
      failureThreshold: 3
      replicas: {{ .Values.runner.hpa.minReplicas }}
    triggers:
      - type: redis
        metadata:
          address: {{ .Values.keda.redisAddress | quote }}
          listName: "arq:queue"
          listLength: "{{ .Values.keda.scaledObject.queueDepthThreshold }}"
          databaseIndex: "0"
          enableTLS: "false"
        authenticationRef:
          name: {{ include "suitest.fullname" . }}-redis-auth
  {{- end }}
  ```
- [ ] **7.2.2** Create `templates/runner-trigger-authentication.yaml` for KEDA TriggerAuthentication referencing the Redis password Secret.

### 7.3 Alternative — Prometheus-based ScaledObject

- [ ] **7.3.1** Provide alternative trigger config in values for users who already have Prometheus stack:
  ```yaml
  keda:
    triggerType: prometheus  # or "redis"
    prometheus:
      serverAddress: http://prometheus.monitoring.svc:9090
      query: max(suitest_runs_queue_depth)
      threshold: "10"
  ```
- [ ] **7.3.2** Template conditional `{{- if eq .Values.keda.triggerType "prometheus" }} ... {{- end }}`.

### 7.4 API HPA on cpu/memory (already from Task 6) — verify

- [ ] **7.4.1** Confirm `api-hpa.yaml` includes both cpu and memory metrics. Add memory metric block:
  ```yaml
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  ```

### 7.5 Tests

- [ ] **7.5.1** `helm template suitest . --set keda.enabled=true` → output includes `kind: ScaledObject`. Pytest in `tests/unit/test_helm_render.py`:
  ```python
  import subprocess, yaml
  def test_keda_scaledobject_renders_when_enabled():
      out = subprocess.check_output([
          "helm", "template", "suitest", "infra/helm/suitest",
          "--set", "keda.enabled=true",
          "--set", "keda.redisAddress=redis.default:6379",
      ], text=True)
      docs = list(yaml.safe_load_all(out))
      kinds = {d.get("kind") for d in docs if d}
      assert "ScaledObject" in kinds
  ```
- [ ] **7.5.2** `helm template suitest . --set keda.enabled=false` → no ScaledObject.

- [ ] **7.6** Commit: `feat(helm): KEDA scaledobject for runner queue-depth scaling (Closes #M4-3)`.

---

## Task 8: NetworkPolicy + cert-manager Ingress

Default-deny + explicit allowlist + TLS via cert-manager.

### 8.1 NetworkPolicy templates

- [ ] **8.1.1** Create `templates/networkpolicy-default-deny.yaml`:
  ```yaml
  {{- if .Values.networkPolicy.defaultDeny }}
  apiVersion: networking.k8s.io/v1
  kind: NetworkPolicy
  metadata:
    name: {{ include "suitest.fullname" . }}-default-deny
    labels: {{- include "suitest.labels" . | nindent 4 }}
  spec:
    podSelector: {}
    policyTypes: [Ingress, Egress]
  {{- end }}
  ```
- [ ] **8.1.2** Create `templates/networkpolicy-api.yaml` — allow:
  - Ingress from web pods on 8000
  - Ingress from runner pods (callbacks) on 8000
  - Ingress from ingress-controller namespace on 8000
  - Egress to postgres/redis/minio (label-selector + port)
  - Egress to DNS (UDP 53)
  - Egress to LLM hosts (when `allowLLM=true`): use `.Values.networkPolicy.egress.allowLLMHosts` rendered as `egress.to.ipBlock` (cluster-DNS resolves FQDN at NetworkPolicy controller level — Calico/Cilium support FQDN; vanilla doesn't, so document this caveat)
- [ ] **8.1.3** Create `templates/networkpolicy-runner.yaml` — allow:
  - Egress to api 8000
  - Egress to Redis (queue)
  - Egress to MCP server pods (label-based)
  - Egress to MinIO (artifacts)
  - Egress to LLM hosts (LOCAL+CLOUD)
  - Egress to integrations (Jira/Linear/Slack/GitHub) when `allowExternalIntegrations=true`
- [ ] **8.1.4** Create `templates/networkpolicy-web.yaml` — Ingress from ingress-controller only; Egress to api 8000 only.

### 8.2 cert-manager Ingress

- [ ] **8.2.1** Edit `templates/web-ingress.yaml`:
  ```yaml
  {{- if .Values.ingress.enabled }}
  apiVersion: networking.k8s.io/v1
  kind: Ingress
  metadata:
    name: {{ include "suitest.fullname" . }}
    labels: {{- include "suitest.labels" . | nindent 4 }}
    annotations:
      {{- if .Values.certManager.enabled }}
      cert-manager.io/cluster-issuer: {{ .Values.certManager.clusterIssuer | quote }}
      {{- end }}
      nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
      nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
      {{- with .Values.ingress.annotations }}
      {{- toYaml . | nindent 4 }}
      {{- end }}
  spec:
    ingressClassName: {{ .Values.ingress.className | quote }}
    tls:
      {{- range .Values.ingress.tls }}
      - hosts:
          {{- range .hosts }}
          - {{ . | quote }}
          {{- end }}
        secretName: {{ .secretName }}
      {{- end }}
    rules:
      {{- range .Values.ingress.hosts }}
      - host: {{ .host | quote }}
        http:
          paths:
            - path: /api
              pathType: Prefix
              backend:
                service:
                  name: {{ include "suitest.fullname" $ }}-api
                  port: { number: 8000 }
            - path: /ws
              pathType: Prefix
              backend:
                service:
                  name: {{ include "suitest.fullname" $ }}-api
                  port: { number: 8000 }
            - path: /sse
              pathType: Prefix
              backend:
                service:
                  name: {{ include "suitest.fullname" $ }}-api
                  port: { number: 8000 }
            - path: /
              pathType: Prefix
              backend:
                service:
                  name: {{ include "suitest.fullname" $ }}-web
                  port: { number: 80 }
      {{- end }}
  {{- end }}
  ```
- [ ] **8.2.2** Document in `docs/DEPLOYMENT.md` §3.5 — cert-manager prerequisite: `helm install cert-manager jetstack/cert-manager --namespace cert-manager --create-namespace --set installCRDs=true`. ClusterIssuer creation is out-of-scope for the chart (user-provided).

### 8.3 Optional ServiceMesh annotations

- [ ] **8.3.1** Add `.Values.serviceMesh.istio.enabled: false` toggle. When true, add `sidecar.istio.io/inject: "true"` annotation to api/runner/web Pod templates.

### 8.4 Tests

- [ ] **8.4.1** `helm lint` passes with all policies enabled.
- [ ] **8.4.2** Pytest `tests/unit/test_helm_networkpolicy.py`:
  - `--set networkPolicy.defaultDeny=true` → ≥4 NetworkPolicy resources rendered (default-deny + api + runner + web).
  - `--set networkPolicy.defaultDeny=false` → no NetworkPolicy resources.
- [ ] **8.4.3** Pytest `tests/unit/test_helm_ingress.py`:
  - `--set certManager.enabled=true` → ingress has `cert-manager.io/cluster-issuer` annotation.

- [ ] **8.5** Commit: `feat(helm): NetworkPolicy default-deny + cert-manager ingress (Closes #M4-3)`.

---

## Task 9: Air-gapped deploy validation

Prove the chart installs and runs with zero outbound network.

### 9.1 Documentation — air-gap bundle workflow

- [ ] **9.1.1** Create `docs/AIR_GAPPED.md`:
  ```markdown
  # Air-gapped deployment guide

  Suitest supports zero-egress deployment for regulated/disconnected environments.

  ## Prerequisites

  - Internal container registry (Harbor, Artifactory, AWS ECR private, etc.)
  - Internal Helm chart repository
  - Internal package mirror (Alpine apk, PyPI proxy)
  - Internal MCP server bundle image

  ## Image bundle

  Download release bundle from GitHub Releases (signed tarball):

      curl -LO https://github.com/suitest-dev/suitest/releases/download/v1.0.0/suitest-images-v1.0.0.tar.gz
      gpg --verify suitest-images-v1.0.0.tar.gz.sig

  Bundle contains:

  - ghcr.io/suitest-dev/suitest-api:1.0.0
  - ghcr.io/suitest-dev/suitest-runner:1.0.0
  - ghcr.io/suitest-dev/suitest-web:1.0.0
  - ghcr.io/suitest-dev/mcp-bundle:1.0.0
  - bitnami/postgresql:16.4.0
  - bitnami/redis:7.4.0
  - bitnami/minio:2024.8.x
  - ollama/ollama:0.4.0 (optional LOCAL tier)

  Load into internal registry:

      tar xf suitest-images-v1.0.0.tar.gz
      for img in *.tar; do
        docker load -i "$img"
        name=$(docker load -i "$img" | sed 's/Loaded image: //')
        docker tag "$name" internal.corp/suitest/$(basename "$name")
        docker push internal.corp/suitest/$(basename "$name")
      done

  ## Helm install

      helm install suitest oci://internal.corp/charts/suitest --version 1.0.0 \
        --namespace suitest --create-namespace \
        -f values-airgap.yaml

  ## `values-airgap.yaml` example

      suitest:
        tier: zero
      image:
        registry: internal.corp/suitest
        pullSecrets: [{ name: internal-registry }]
      llm:
        provider: none
      embeddings:
        backend: fastembed
      networkPolicy:
        defaultDeny: true
        egress:
          allowLLM: false
          allowExternalIntegrations: false
          allowDns: true
      ingress:
        enabled: true
        className: nginx-internal
      certManager:
        enabled: true
        clusterIssuer: internal-ca

  ## LOCAL tier with bundled Ollama

      llm:
        provider: ollama
        baseUrl: http://suitest-ollama:11434
        model: ollama/llama3.1:8b-instruct
      ollama:
        embedded: true
        image: internal.corp/suitest/ollama:0.4.0
        modelsPreloaded:
          - llama3.1:8b-instruct

  ## Verification checklist

  1. `kubectl get pods -n suitest` → all Running.
  2. `kubectl logs -l app=suitest-api -n suitest | grep capability_resolved` → tier matches expected.
  3. `kubectl run net-test --image=busybox --rm -it -- wget -q -T5 https://api.openai.com` → expect timeout (proves no egress).
  4. Open ingress URL → login → empty dashboard → ZERO badge.
  5. Run smoke suite (Task 23) → green.
  ```

### 9.2 Air-gap dry-run script

- [ ] **9.2.1** Create `tools/airgap-bundle.sh`:
  ```bash
  #!/usr/bin/env bash
  # Build image bundle tarball for air-gap distribution.
  set -euo pipefail
  VERSION="${1:-1.0.0}"
  OUT="suitest-images-v${VERSION}.tar.gz"
  IMAGES=(
    "ghcr.io/suitest-dev/suitest-api:${VERSION}"
    "ghcr.io/suitest-dev/suitest-runner:${VERSION}"
    "ghcr.io/suitest-dev/suitest-web:${VERSION}"
    "ghcr.io/suitest-dev/mcp-bundle:${VERSION}"
    "docker.io/bitnami/postgresql:16.4.0"
    "docker.io/bitnami/redis:7.4.0"
    "docker.io/bitnami/minio:2024.8.x"
  )
  TMP=$(mktemp -d)
  for img in "${IMAGES[@]}"; do
    fname=$(echo "$img" | tr '/:' '_').tar
    docker pull "$img"
    docker save -o "$TMP/$fname" "$img"
  done
  cp infra/helm/suitest "$TMP/helm-chart" -r
  tar czf "$OUT" -C "$TMP" .
  echo "wrote $OUT ($(du -h "$OUT" | cut -f1))"
  rm -rf "$TMP"
  ```
- [ ] **9.2.2** GitHub Actions release job runs this on tag, uploads tarball + GPG signature as release asset.

### 9.3 Air-gap drill — 1-hour disconnected k8s simulation

- [ ] **9.3.1** Create `tools/airgap-drill.sh`:
  ```bash
  #!/usr/bin/env bash
  # 1-hour drill: spin up kind cluster with NO public registry access,
  # load bundle, install chart, verify zero outbound traffic.
  set -euo pipefail

  # 1. Create kind cluster with restricted networking
  cat > /tmp/kind-airgap.yaml <<EOF
  kind: Cluster
  apiVersion: kind.x-k8s.io/v1alpha4
  networking:
    disableDefaultCNI: false
  nodes:
    - role: control-plane
      kubeadmConfigPatches:
        - |
          kind: InitConfiguration
          nodeRegistration:
            kubeletExtraArgs:
              node-labels: "ingress-ready=true"
  containerdConfigPatches:
    # block public registries by pointing them at a sinkhole
    - |
      [plugins."io.containerd.grpc.v1.cri".registry.mirrors."docker.io"]
        endpoint = ["http://127.0.0.1:5000"]
      [plugins."io.containerd.grpc.v1.cri".registry.mirrors."ghcr.io"]
        endpoint = ["http://127.0.0.1:5000"]
  EOF
  kind create cluster --name suitest-airgap --config /tmp/kind-airgap.yaml

  # 2. Local registry on 5000
  docker run -d --name local-registry --restart always -p 5000:5000 registry:2
  docker network connect kind local-registry

  # 3. Push bundle into local registry
  for img in $(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E 'suitest|bitnami'); do
    target="localhost:5000/$(echo "$img" | sed 's|.*/||')"
    docker tag "$img" "$target"
    docker push "$target"
  done

  # 4. Install Helm chart pointing at local registry
  helm install suitest infra/helm/suitest \
    --namespace suitest --create-namespace \
    --set image.registry=localhost:5000 \
    -f infra/helm/suitest/values-airgap.yaml

  # 5. Wait for ready
  kubectl wait --for=condition=Available --timeout=300s deployment -n suitest -l app.kubernetes.io/name=suitest

  # 6. Verify no egress with NetworkPolicy
  kubectl run egress-test --image=busybox --rm -i --restart=Never -- sh -c 'wget -q -T5 https://api.openai.com 2>&1 | grep -q "timed out\|bad address"; echo "EGRESS_BLOCKED=$?"'

  # 7. Smoke suite
  bash tools/smoke-suite.sh

  # 8. Teardown
  kind delete cluster --name suitest-airgap
  docker rm -f local-registry
  ```
- [ ] **9.3.2** Add to CI as a weekly scheduled job (`.github/workflows/airgap-drill.yml`), runs every Sunday 02:00 UTC.

### 9.4 Bundled MCP image

- [ ] **9.4.1** Create `infra/docker/mcp-bundle/Dockerfile`:
  ```dockerfile
  # Bundles all v1.0 default MCP server binaries for air-gap deploy.
  FROM python:3.12-slim AS builder
  RUN pip install --no-cache-dir \
      "mcp-server-playwright>=0.4.0" \
      "mcp-server-postgres>=0.4.0" \
      "mcp-server-graphql>=0.4.0" \
      "mcp-server-mongodb>=0.4.0" \
      "mcp-server-mysql>=0.4.0" \
      "mcp-server-kubernetes>=0.4.0" \
      "mcp-server-grpc>=0.4.0"

  FROM python:3.12-slim
  COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
  COPY --from=builder /usr/local/bin/mcp-server-* /usr/local/bin/
  # Playwright browsers
  RUN pip install --no-cache-dir playwright && playwright install --with-deps chromium
  CMD ["mcp-server-playwright"]
  ```
- [ ] **9.4.2** Build + tag + push as part of release CI workflow.

### 9.5 Validation

- [ ] **9.5.1** Manual drill log — record one full disconnected k8s install. Capture in `docs/AIR_GAPPED.md` §"Verified deployments" — date + cluster size + observed network policy + smoke results. First entry: v1.0.0 release.
- [ ] **9.5.2** Verify `tier=zero, networkPolicy.egress.allowLLM=false` results in zero outbound HTTPS traffic during 1-hour soak test (run smoke suite continuously). Use `tcpdump -nn -i any 'tcp port 443 and not net 10.0.0.0/8'` from node.

- [ ] **9.6** Commit: `feat(helm): air-gap deployment bundle + drill (Closes #M4-4)`.

---

## Task 10: SDK — Python (`suitest-py`)

Auto-generated typed client from OpenAPI.

### 10.1 Package skeleton

- [ ] **10.1.1** Create `packages/sdk-py/pyproject.toml`:
  ```toml
  [project]
  name = "suitest-py"
  version = "1.0.0"
  description = "Python SDK for Suitest — MCP-native testing platform"
  readme = "README.md"
  authors = [{ name = "Suitest Maintainers", email = "maintainers@suitest.dev" }]
  license = { text = "Apache-2.0" }
  requires-python = ">=3.10"
  dependencies = [
      "httpx>=0.27",
      "pydantic>=2.6",
      "typing-extensions>=4.10",
      "websockets>=12.0",
  ]
  classifiers = [
      "License :: OSI Approved :: Apache Software License",
      "Programming Language :: Python :: 3.10",
      "Programming Language :: Python :: 3.11",
      "Programming Language :: Python :: 3.12",
      "Topic :: Software Development :: Testing",
  ]

  [project.urls]
  Homepage = "https://suitest.dev"
  Repository = "https://github.com/suitest-dev/suitest"
  Documentation = "https://suitest.dev/docs/sdk-py"

  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"

  [tool.hatch.build.targets.wheel]
  packages = ["src/suitest"]
  ```
- [ ] **10.1.2** Create `packages/sdk-py/README.md` with quickstart + API summary.

### 10.2 Generate base client from OpenAPI

- [ ] **10.2.1** Add `Makefile` rule at repo root:
  ```makefile
  .PHONY: sdk-py
  sdk-py:
  	# Snapshot OpenAPI from running api (or use committed packages/shared/openapi.json)
  	mkdir -p packages/shared
  	if [ -z "$(SUITEST_API_URL)" ]; then \
  	  echo "Using committed openapi.json"; \
  	else \
  	  curl -fsSL "$(SUITEST_API_URL)/openapi.json" -o packages/shared/openapi.json; \
  	fi
  	cd packages/sdk-py && rm -rf src/suitest/_generated && \
  	  openapi-python-client generate \
  	    --path ../shared/openapi.json \
  	    --config sdk-py-config.yaml \
  	    --custom-template-path templates/
  ```
- [ ] **10.2.2** Create `packages/sdk-py/sdk-py-config.yaml`:
  ```yaml
  package_name_override: suitest._generated
  project_name_override: suitest-py
  use_path_prefixes_for_title_model_names: true
  field_prefix: _
  ```
- [ ] **10.2.3** Commit `packages/shared/openapi.json` to repo — regenerated and committed on every release (Task 28).

### 10.3 High-level convenience wrappers

- [ ] **10.3.1** Create `packages/sdk-py/src/suitest/__init__.py`:
  ```python
  """Suitest SDK — typed client for Suitest API."""
  from suitest.client import SuitestClient, AsyncSuitestClient
  from suitest._generated.models import (
      TestCase, TestRun, RunOutcome, AgentSession,
      McpProvider, Capabilities,
  )
  __version__ = "1.0.0"
  __all__ = [
      "SuitestClient", "AsyncSuitestClient",
      "TestCase", "TestRun", "RunOutcome", "AgentSession",
      "McpProvider", "Capabilities",
  ]
  ```
- [ ] **10.3.2** Create `packages/sdk-py/src/suitest/client.py`:
  ```python
  from __future__ import annotations
  import os, asyncio
  from typing import AsyncIterator, Iterator
  import httpx
  from suitest._generated.client import AuthenticatedClient, Client
  from suitest._generated.api.runs import start_run, get_run, watch_run
  from suitest._generated.api.cases import list_cases, get_case, create_case
  from suitest._generated.api.capabilities import get_capabilities
  from suitest._generated.models import (
      TestCase, TestRun, RunOutcome, Capabilities, RunStartRequest,
  )

  class SuitestClient:
      """Sync facade."""
      def __init__(self, base_url: str | None = None, token: str | None = None, timeout: float = 30.0):
          self._base = base_url or os.environ["SUITEST_API_URL"]
          self._token = token or os.environ.get("SUITEST_TOKEN")
          self._inner = (
              AuthenticatedClient(base_url=self._base, token=self._token, timeout=timeout)
              if self._token else
              Client(base_url=self._base, timeout=timeout)
          )

      @property
      def runs(self) -> "RunsResource": return RunsResource(self._inner)

      @property
      def cases(self) -> "CasesResource": return CasesResource(self._inner)

      def capabilities(self) -> Capabilities:
          return get_capabilities.sync(client=self._inner)

  class RunsResource:
      def __init__(self, client): self._c = client
      def start(self, *, suite_id: str | None = None, case_ids: list[str] | None = None,
                tag: str | None = None, branch: str | None = None, commit: str | None = None) -> TestRun:
          req = RunStartRequest(suite_id=suite_id, case_ids=case_ids or [], tag=tag, branch=branch, commit=commit)
          return start_run.sync(client=self._c, body=req)
      def get(self, run_id: str) -> TestRun:
          return get_run.sync(client=self._c, run_id=run_id)
      def watch(self, run_id: str) -> Iterator[dict]:
          """Synchronous SSE iterator over run events."""
          with httpx.Client(base_url=self._c.base_url, timeout=None) as h:
              with h.stream("GET", f"/api/v1/runs/{run_id}/events", headers=self._c.get_headers()) as r:
                  for line in r.iter_lines():
                      if line.startswith("data: "):
                          import json
                          yield json.loads(line.removeprefix("data: "))

  class CasesResource:
      def __init__(self, client): self._c = client
      def list(self, *, workspace_id: str, limit: int = 50, cursor: str | None = None) -> list[TestCase]:
          return list_cases.sync(client=self._c, workspace_id=workspace_id, limit=limit, cursor=cursor).items
      def get(self, case_id: str) -> TestCase:
          return get_case.sync(client=self._c, case_id=case_id)
      def create(self, case: TestCase) -> TestCase:
          return create_case.sync(client=self._c, body=case)
  ```
- [ ] **10.3.3** Create `AsyncSuitestClient` mirror with `httpx.AsyncClient` and `async for` event iteration via `asyncio` + `aiohttp-sse-client`.

### 10.4 WebSocket helper

- [ ] **10.4.1** Add `packages/sdk-py/src/suitest/ws.py`:
  ```python
  from __future__ import annotations
  import asyncio, json
  from typing import AsyncIterator
  import websockets

  async def subscribe(ws_url: str, token: str, channels: list[str]) -> AsyncIterator[dict]:
      """Yield decoded JSON envelopes from a server WS push channel."""
      async with websockets.connect(f"{ws_url}?token={token}") as ws:
          for ch in channels:
              await ws.send(json.dumps({"type": f"subscribe.{ch}"}))
          async for raw in ws:
              yield json.loads(raw)
  ```

### 10.5 Build + publish CI

- [ ] **10.5.1** GitHub Actions workflow `.github/workflows/release-sdk-py.yml`:
  ```yaml
  name: release-sdk-py
  on:
    push:
      tags: ["sdk-py/v*"]
  jobs:
    publish:
      runs-on: ubuntu-latest
      permissions:
        id-token: write  # trusted publishing
      steps:
        - uses: actions/checkout@v4
        - uses: astral-sh/setup-uv@v3
        - run: make sdk-py
        - run: cd packages/sdk-py && uv build
        - uses: pypa/gh-action-pypi-publish@release/v1
          with:
            packages-dir: packages/sdk-py/dist
  ```
- [ ] **10.5.2** PyPI trusted publishing configured against suitest-py PyPI project.

### 10.6 Quickstart example

- [ ] **10.6.1** Create `examples/sdk-py-quickstart/`:
  - `README.md` — install + usage
  - `quickstart.py`:
    ```python
    from suitest import SuitestClient
    c = SuitestClient()
    caps = c.capabilities()
    print(f"Tier: {caps.tier}, autonomy: {caps.autonomy.default}")
    cases = c.cases.list(workspace_id="ws_nusantara")
    print(f"{len(cases)} cases in workspace")
    run = c.runs.start(suite_id=cases[0].suite_id, tag="sdk-smoke")
    for ev in c.runs.watch(run.id):
        print(ev["type"], ev.get("data", {}).get("step_index"))
        if ev["type"] == "run.completed":
            break
    ```

### 10.7 Tests

- [ ] **10.7.1** `packages/sdk-py/tests/test_client_smoke.py`:
  - Boot ephemeral suitest-api via docker-compose.
  - `c = SuitestClient()`, fetch capabilities → assert tier == "ZERO".
  - Create case, fetch case, assert round-trip.
- [ ] **10.7.2** `packages/sdk-py/tests/test_generated_models.py` — assert key models import + match expected shape after regeneration.

- [ ] **10.8** Commit: `feat(sdk-py): Python SDK + PyPI release pipeline (Closes #M4-5)`.

---

## Task 11: SDK — TypeScript (`@suitest/sdk`)

### 11.1 Package skeleton

- [ ] **11.1.1** Create `packages/sdk-ts/package.json`:
  ```json
  {
    "name": "@suitest/sdk",
    "version": "1.0.0",
    "description": "TypeScript SDK for Suitest",
    "license": "Apache-2.0",
    "type": "module",
    "main": "./dist/index.cjs",
    "module": "./dist/index.js",
    "types": "./dist/index.d.ts",
    "exports": {
      ".": {
        "import": "./dist/index.js",
        "require": "./dist/index.cjs",
        "types": "./dist/index.d.ts"
      }
    },
    "files": ["dist", "README.md", "LICENSE"],
    "scripts": {
      "generate": "openapi --input ../shared/openapi.json --output src/_generated --client fetch --useUnionTypes",
      "build": "tsup src/index.ts --format cjs,esm --dts --clean",
      "test": "vitest run",
      "prepublishOnly": "pnpm generate && pnpm build"
    },
    "devDependencies": {
      "openapi-typescript-codegen": "^0.29.0",
      "tsup": "^8.0.0",
      "typescript": "^5.5.0",
      "vitest": "^2.0.0"
    },
    "engines": { "node": ">=18" }
  }
  ```

### 11.2 Generated client + facade

- [ ] **11.2.1** `make sdk-ts` rule mirrors `make sdk-py`:
  ```makefile
  .PHONY: sdk-ts
  sdk-ts:
  	cd packages/sdk-ts && pnpm install --frozen-lockfile && pnpm generate
  ```
- [ ] **11.2.2** `packages/sdk-ts/src/index.ts` exports:
  ```ts
  export { SuitestClient } from "./client";
  export type { TestCase, TestRun, Capabilities, AgentSession, McpProvider, RunOutcome } from "./_generated/models";
  export { ApiError } from "./_generated/core/ApiError";
  ```
- [ ] **11.2.3** `packages/sdk-ts/src/client.ts`:
  ```ts
  import { OpenAPI, DefaultService } from "./_generated";
  import type { TestCase, TestRun, Capabilities, RunStartRequest } from "./_generated/models";
  import { runsWatch } from "./sse";
  import { wsSubscribe } from "./ws";

  export interface SuitestClientOptions {
    baseUrl?: string;
    token?: string;
    timeoutMs?: number;
  }

  export class SuitestClient {
    constructor(opts: SuitestClientOptions = {}) {
      OpenAPI.BASE = opts.baseUrl ?? process.env.SUITEST_API_URL ?? "";
      if (opts.token ?? process.env.SUITEST_TOKEN)
        OpenAPI.TOKEN = opts.token ?? process.env.SUITEST_TOKEN;
    }
    capabilities = (): Promise<Capabilities> => DefaultService.getCapabilities();
    runs = {
      start: (req: RunStartRequest): Promise<TestRun> => DefaultService.startRun({ requestBody: req }),
      get:   (id: string): Promise<TestRun>            => DefaultService.getRun({ runId: id }),
      watch: (id: string)                              => runsWatch(OpenAPI.BASE!, OpenAPI.TOKEN as string | undefined, id),
    };
    cases = {
      list: (workspaceId: string, params?: { limit?: number; cursor?: string }) =>
        DefaultService.listCases({ workspaceId, ...params }),
      get:    (id: string) => DefaultService.getCase({ caseId: id }),
      create: (body: TestCase) => DefaultService.createCase({ requestBody: body }),
    };
    ws = (channels: string[]) => wsSubscribe(OpenAPI.BASE!, OpenAPI.TOKEN as string | undefined, channels);
  }
  ```
- [ ] **11.2.4** `packages/sdk-ts/src/sse.ts` — `async function*` consuming `EventSource` (browser) or `eventsource-parser` lib (Node).
- [ ] **11.2.5** `packages/sdk-ts/src/ws.ts` — uses `isows` for browser+Node compatibility.

### 11.3 npm publish CI

- [ ] **11.3.1** `.github/workflows/release-sdk-ts.yml`:
  ```yaml
  name: release-sdk-ts
  on:
    push:
      tags: ["sdk-ts/v*"]
  jobs:
    publish:
      runs-on: ubuntu-latest
      permissions:
        id-token: write  # npm provenance
      steps:
        - uses: actions/checkout@v4
        - uses: pnpm/action-setup@v4
        - uses: actions/setup-node@v4
          with:
            node-version: '20'
            registry-url: 'https://registry.npmjs.org'
        - run: pnpm install --frozen-lockfile
        - run: pnpm --filter @suitest/sdk run build
        - run: pnpm --filter @suitest/sdk publish --provenance --access public
          env:
            NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
  ```

### 11.4 Quickstart example

- [ ] **11.4.1** Create `examples/sdk-ts-quickstart/`:
  - `package.json` with `@suitest/sdk` dep.
  - `index.ts`:
    ```ts
    import { SuitestClient } from "@suitest/sdk";
    const c = new SuitestClient();
    const caps = await c.capabilities();
    console.log(`Tier: ${caps.tier}, autonomy: ${caps.autonomy.default}`);
    const { items: cases } = await c.cases.list("ws_nusantara");
    const run = await c.runs.start({ suite_id: cases[0]!.suite_id!, tag: "sdk-smoke" });
    for await (const ev of c.runs.watch(run.id)) {
      console.log(ev.type, (ev.data as any)?.step_index);
      if (ev.type === "run.completed") break;
    }
    ```

### 11.5 Tests

- [ ] **11.5.1** `packages/sdk-ts/tests/client.smoke.test.ts` (vitest):
  - Ephemeral api docker-compose.
  - `new SuitestClient({ baseUrl: ... })`.
  - `capabilities()` → tier === "ZERO".
  - Round-trip case create + fetch.
- [ ] **11.5.2** `tsc --noEmit` passes on generated client.

- [ ] **11.6** Commit: `feat(sdk-ts): TypeScript SDK + npm release pipeline (Closes #M4-5)`.

---

## Task 12: CLI — `suitest`

### 12.1 Package skeleton

- [ ] **12.1.1** Create `apps/cli/pyproject.toml`:
  ```toml
  [project]
  name = "suitest"
  version = "1.0.0"
  description = "Suitest command-line interface"
  readme = "README.md"
  license = { text = "Apache-2.0" }
  requires-python = ">=3.10"
  dependencies = [
      "suitest-py>=1.0.0",
      "typer>=0.12",
      "rich>=13.7",
      "tomli>=2.0; python_version < '3.11'",
      "tomli-w>=1.0",
      "httpx>=0.27",
  ]

  [project.scripts]
  suitest = "suitest_cli.main:app"

  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"

  [tool.hatch.build.targets.wheel]
  packages = ["src/suitest_cli"]
  ```
- [ ] **12.1.2** `apps/cli/src/suitest_cli/__init__.py` (empty docstring).

### 12.2 Config file + auth flow

- [ ] **12.2.1** Create `apps/cli/src/suitest_cli/config.py`:
  ```python
  from __future__ import annotations
  import os, sys, tomli, tomli_w
  from pathlib import Path
  from dataclasses import dataclass

  CONFIG_PATH = Path.home() / ".suitest" / "config.toml"

  @dataclass
  class CliConfig:
      api_url: str
      token: str | None = None
      workspace_id: str | None = None

      @classmethod
      def load(cls) -> "CliConfig":
          env_url = os.environ.get("SUITEST_API_URL")
          env_token = os.environ.get("SUITEST_TOKEN")
          env_ws = os.environ.get("SUITEST_WORKSPACE_ID")
          file_cfg = {}
          if CONFIG_PATH.exists():
              with CONFIG_PATH.open("rb") as f:
                  file_cfg = tomli.load(f)
          api_url = env_url or file_cfg.get("api_url")
          if not api_url:
              sys.exit("error: SUITEST_API_URL not set. Run `suitest login` or set env var.")
          return cls(
              api_url=api_url,
              token=env_token or file_cfg.get("token"),
              workspace_id=env_ws or file_cfg.get("workspace_id"),
          )

      def save(self) -> None:
          CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
          data = {"api_url": self.api_url}
          if self.token: data["token"] = self.token
          if self.workspace_id: data["workspace_id"] = self.workspace_id
          with CONFIG_PATH.open("wb") as f:
              tomli_w.dump(data, f)
          CONFIG_PATH.chmod(0o600)
  ```

### 12.3 Commands

- [ ] **12.3.1** Create `apps/cli/src/suitest_cli/main.py`:
  ```python
  from __future__ import annotations
  import sys, typer
  from rich.console import Console
  from rich.table import Table
  from suitest import SuitestClient
  from suitest_cli.config import CliConfig
  from suitest_cli import cmd_run, cmd_case, cmd_generate, cmd_export, cmd_replay, cmd_login

  app = typer.Typer(name="suitest", help="Suitest CLI — MCP-native testing platform", no_args_is_help=True)
  console = Console()

  app.command(name="login")(cmd_login.login)
  app.command(name="run")(cmd_run.run_cmd)
  case_app = typer.Typer(name="case", help="Test case operations")
  case_app.command("list")(cmd_case.list_cases)
  app.add_typer(case_app)
  gen_app = typer.Typer(name="generate", help="Run generators")
  gen_app.command("openapi")(cmd_generate.openapi)
  app.add_typer(gen_app)
  app.command(name="export")(cmd_export.export_case)
  app.command(name="replay")(cmd_replay.replay)

  if __name__ == "__main__":
      app()
  ```
- [ ] **12.3.2** `apps/cli/src/suitest_cli/cmd_login.py`:
  ```python
  import typer
  from suitest_cli.config import CliConfig, CONFIG_PATH

  def login(
      api_url: str = typer.Option(..., "--api-url", "-u", help="Suitest API base URL"),
      token: str = typer.Option(..., "--token", "-t", help="API token", prompt=True, hide_input=True),
      workspace_id: str = typer.Option(None, "--workspace", "-w", help="Default workspace id"),
  ) -> None:
      cfg = CliConfig(api_url=api_url, token=token, workspace_id=workspace_id)
      cfg.save()
      typer.echo(f"Saved config to {CONFIG_PATH}")
  ```
- [ ] **12.3.3** `apps/cli/src/suitest_cli/cmd_run.py`:
  ```python
  import typer
  from rich.live import Live
  from rich.console import Console
  from suitest import SuitestClient
  from suitest_cli.config import CliConfig
  console = Console()

  def run_cmd(
      suite: str = typer.Option(None, "--suite", "-s", help="Suite id or name"),
      case_id: list[str] = typer.Option(None, "--case", "-c", help="Specific case id (repeatable)"),
      branch: str = typer.Option(None, "--branch", "-b"),
      commit: str = typer.Option(None, "--commit"),
      tag: str = typer.Option(None, "--tag"),
      follow: bool = typer.Option(True, "--follow/--no-follow"),
  ) -> None:
      cfg = CliConfig.load()
      c = SuitestClient(base_url=cfg.api_url, token=cfg.token)
      run = c.runs.start(suite_id=suite, case_ids=case_id, branch=branch, commit=commit, tag=tag)
      typer.echo(f"Started run {run.id}")
      if not follow:
          return
      for ev in c.runs.watch(run.id):
          console.print(f"[{ev['type']}] step={ev.get('data', {}).get('step_index')} status={ev.get('data', {}).get('status')}")
          if ev["type"] == "run.completed":
              outcome = ev["data"]["outcome"]
              if outcome == "pass":
                  console.print("[green]PASS[/green]"); raise typer.Exit(0)
              if outcome == "partial_skip":
                  console.print("[yellow]PARTIAL_SKIP[/yellow]"); raise typer.Exit(0)
              console.print(f"[red]{outcome.upper()}[/red]"); raise typer.Exit(1)
  ```
- [ ] **12.3.4** `apps/cli/src/suitest_cli/cmd_case.py` — `list_cases` renders Rich table.
- [ ] **12.3.5** `apps/cli/src/suitest_cli/cmd_generate.py` — `openapi(spec_url: str, project_id: str)` calls `POST /generators/openapi`.
- [ ] **12.3.6** `apps/cli/src/suitest_cli/cmd_export.py` — `export_case(case_id: str, target: str)` calls `GET /test-cases/:id/export?target=...` and writes to stdout or `-o file`.
- [ ] **12.3.7** `apps/cli/src/suitest_cli/cmd_replay.py` — `replay(run_id: str)` opens browser to UI replay URL OR streams replay events to stdout if `--no-browser`.

### 12.4 Build + publish

- [ ] **12.4.1** `uv build apps/cli` produces wheel + sdist.
- [ ] **12.4.2** Workflow `.github/workflows/release-cli.yml` mirrors sdk-py — tag `cli/v*` triggers PyPI publish as package `suitest`.

### 12.5 Tests

- [ ] **12.5.1** `apps/cli/tests/test_cli_smoke.py` using `typer.testing.CliRunner`:
  ```python
  from typer.testing import CliRunner
  from suitest_cli.main import app

  def test_help_runs():
      r = CliRunner().invoke(app, ["--help"])
      assert r.exit_code == 0
      assert "Suitest CLI" in r.stdout

  def test_login_writes_config(tmp_path, monkeypatch):
      monkeypatch.setenv("HOME", str(tmp_path))
      r = CliRunner().invoke(app, ["login", "--api-url", "http://localhost:8000", "--token", "secret-123"])
      assert r.exit_code == 0
      cfg_file = tmp_path / ".suitest" / "config.toml"
      assert cfg_file.exists()
      assert "secret-123" in cfg_file.read_text()
      assert oct(cfg_file.stat().st_mode)[-3:] == "600"
  ```
- [ ] **12.5.2** `apps/cli/tests/test_cli_run_smoke.py` — integration test against running api.

- [ ] **12.6** Commit: `feat(cli): suitest CLI with login/run/case/generate/export/replay (Closes #M4-7)`.

---

## Task 13: Eval harness backend

Orchestrate eval runs against golden fixtures; score generated cases, latency, cost.

### 13.1 Fixtures directory layout

- [ ] **13.1.1** Create `eval/fixtures/` at repo root with structure:
  ```
  eval/fixtures/
  ├── prds/
  │   ├── checkout.md
  │   ├── auth-signup.md
  │   ├── ...
  │   └── checkout.expected.yaml
  ├── openapi/
  │   ├── petstore.json
  │   ├── stripe-mini.yaml
  │   └── petstore.expected.yaml
  └── failed_runs/
      ├── flaky-selector.json
      ├── auth-401.json
      └── flaky-selector.expected.yaml
  ```
- [ ] **13.1.2** Seed initial 20 PRDs: checkout, signup, login, password-reset, 2FA, profile-edit, cart, search, filters, pagination, settings, notifications, file-upload, comments, likes, follow, share, export-csv, billing-toggle, delete-account. Mix of FE_WEB and BE_REST targets.
- [ ] **13.1.3** Seed 10 OpenAPI specs: petstore, stripe-mini, github-mini, suitest-self (own openapi.json), httpbin, jsonplaceholder, openai-mini, anthropic-mini, k8s-mini, mongo-rest-mini.
- [ ] **13.1.4** Seed 15 failed runs: flaky-selector, timeout-network, assertion-mismatch, db-deadlock, race-condition, missing-element, stale-cookie, 401-unauthorized, 500-server-error, 429-rate-limit, dns-resolution, ssl-cert, slow-response, memory-oom, partial-skip-no-llm.
- [ ] **13.1.5** Each `.expected.yaml` declares the expected output shape (NOT exact text — LLM non-deterministic):
  ```yaml
  fixture: checkout
  expected:
    cases_min: 3
    cases_max: 8
    required_step_actions:
      - "add to cart"
      - "checkout"
      - "payment"
    required_assertions_keywords: ["order", "confirmation"]
    target_kind: FE_WEB
  scoring:
    structure_weight: 0.6
    keyword_weight: 0.4
  ```

### 13.2 Eval runner module

- [ ] **13.2.1** Create `packages/agent/src/suitest_agent/eval/__init__.py` (empty docstring).
- [ ] **13.2.2** Create `packages/agent/src/suitest_agent/eval/scorer.py`:
  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any
  import yaml

  @dataclass
  class FixtureScore:
      fixture_name: str
      structure_score: float       # 0..1
      keyword_score: float          # 0..1
      total_score: float            # weighted
      latency_ms: int
      cost_usd: float
      tokens_in: int
      tokens_out: int
      passed: bool
      reasons: list[str]

  def score_fixture(expected_yaml: dict, generated_cases: list[dict], latency_ms: int, cost_usd: float, tokens_in: int, tokens_out: int) -> FixtureScore:
      reasons: list[str] = []
      exp = expected_yaml["expected"]
      weights = expected_yaml.get("scoring", {"structure_weight": 0.6, "keyword_weight": 0.4})
      n = len(generated_cases)
      structure_ok = exp["cases_min"] <= n <= exp["cases_max"]
      if not structure_ok:
          reasons.append(f"case_count={n} outside [{exp['cases_min']},{exp['cases_max']}]")
      structure_score = 1.0 if structure_ok else 0.0

      # keyword presence
      all_text = " ".join(
          (c.get("title", "") + " " + " ".join(s.get("action","") + " " + s.get("expected","")
                                                for s in c.get("steps", []))).lower()
          for c in generated_cases
      )
      keywords_required = exp.get("required_assertions_keywords", []) + exp.get("required_step_actions", [])
      hits = sum(1 for kw in keywords_required if kw.lower() in all_text)
      keyword_score = hits / max(1, len(keywords_required))
      if hits < len(keywords_required):
          reasons.append(f"missing {len(keywords_required) - hits} required keywords")
      total = weights["structure_weight"] * structure_score + weights["keyword_weight"] * keyword_score
      return FixtureScore(
          fixture_name=expected_yaml["fixture"],
          structure_score=structure_score, keyword_score=keyword_score, total_score=total,
          latency_ms=latency_ms, cost_usd=cost_usd, tokens_in=tokens_in, tokens_out=tokens_out,
          passed=total >= 0.7, reasons=reasons,
      )
  ```
- [ ] **13.2.3** Create `packages/agent/src/suitest_agent/eval/runner.py`:
  ```python
  from __future__ import annotations
  import asyncio, time, yaml, json
  from pathlib import Path
  from suitest_agent.graphs.generation import build_generation_graph
  from suitest_agent.eval.scorer import FixtureScore, score_fixture

  async def run_eval(fixture_set: str, workspace_id: str, model_id: str | None = None) -> list[FixtureScore]:
      fixtures_dir = Path("eval/fixtures") / fixture_set
      results: list[FixtureScore] = []
      graph = build_generation_graph()
      for expected_file in fixtures_dir.glob("*.expected.yaml"):
          name = expected_file.stem.removesuffix(".expected")
          expected = yaml.safe_load(expected_file.read_text())
          input_file = expected_file.with_suffix("").with_suffix(".md" if fixture_set == "prds" else ".json")
          input_text = input_file.read_text()
          start = time.monotonic()
          state = await graph.ainvoke({
              "source": fixture_set,
              "input": input_text,
              "workspace_id": workspace_id,
              "model_id": model_id,
          })
          latency_ms = int((time.monotonic() - start) * 1000)
          score = score_fixture(
              expected_yaml=expected,
              generated_cases=state["cases"],
              latency_ms=latency_ms,
              cost_usd=state.get("cost_usd", 0.0),
              tokens_in=state.get("tokens_in", 0),
              tokens_out=state.get("tokens_out", 0),
          )
          results.append(score)
      return results
  ```

### 13.3 API endpoints

- [ ] **13.3.1** Create `apps/api/src/suitest_api/routers/eval.py`:
  ```python
  from fastapi import APIRouter, Depends, BackgroundTasks
  from suitest_core.capabilities import Tier
  from suitest_api.deps.tier import require_tier
  from suitest_api.deps.auth import current_user_admin
  from suitest_api.schemas.eval import EvalRunStartRequest, EvalRunResponse
  from suitest_api.services.eval_service import EvalService

  router = APIRouter(prefix="/eval", tags=["eval"])

  @router.post("/runs", response_model=EvalRunResponse, status_code=201,
               dependencies=[Depends(require_tier(Tier.LOCAL | Tier.CLOUD))])
  async def start_eval(
      body: EvalRunStartRequest,
      background: BackgroundTasks,
      user=Depends(current_user_admin),
      svc: EvalService = Depends(EvalService.dep),
  ) -> EvalRunResponse:
      run = await svc.create_run(workspace_id=user.workspace_id, suite_name=body.suite_name,
                                  fixture_set=body.fixture_set, user_id=user.id,
                                  model_id=body.model_id)
      background.add_task(svc.execute_run, run.id)
      return EvalRunResponse.from_model(run)

  @router.get("/runs/{run_id}", response_model=EvalRunResponse,
              dependencies=[Depends(require_tier(Tier.LOCAL | Tier.CLOUD))])
  async def get_eval(run_id: str, user=Depends(current_user_admin),
                     svc: EvalService = Depends(EvalService.dep)) -> EvalRunResponse:
      return EvalRunResponse.from_model(await svc.get_run(user.workspace_id, run_id))

  @router.get("/runs", dependencies=[Depends(require_tier(Tier.LOCAL | Tier.CLOUD))])
  async def list_eval_runs(suite_name: str | None = None, user=Depends(current_user_admin),
                            svc: EvalService = Depends(EvalService.dep)) -> list[EvalRunResponse]:
      runs = await svc.list_runs(user.workspace_id, suite_name=suite_name)
      return [EvalRunResponse.from_model(r) for r in runs]
  ```
- [ ] **13.3.2** Create `apps/api/src/suitest_api/services/eval_service.py` — orchestrates eval, persists EvalRun, computes aggregate score, fires Prometheus metric `suitest_eval_score{suite, fixture_set, provider}`.
- [ ] **13.3.3** Create Pydantic schemas in `apps/api/src/suitest_api/schemas/eval.py`.

### 13.4 Scheduled weekly job

- [ ] **13.4.1** Create `apps/runner/src/suitest_runner/jobs/eval_scheduled.py`:
  ```python
  from arq import cron
  async def run_weekly_eval(ctx: dict) -> None:
      # Run for each workspace that has LLM configured AND has opted-in to eval
      from suitest_db.repositories.workspace_capability_repo import WorkspaceCapabilityRepo
      async with ctx["db"]() as session:
          repo = WorkspaceCapabilityRepo(session)
          eligible = await repo.list_with_llm_and_eval_enabled()
      for ws in eligible:
          from suitest_runner.jobs.run_eval_workspace import run_eval_workspace_job
          await ctx["arq_redis"].enqueue_job("run_eval_workspace_job", ws.id, "prds")
          await ctx["arq_redis"].enqueue_job("run_eval_workspace_job", ws.id, "openapi")
          await ctx["arq_redis"].enqueue_job("run_eval_workspace_job", ws.id, "failed_runs")
  ```
- [ ] **13.4.2** Register cron in `apps/runner/src/suitest_runner/worker.py`:
  ```python
  cron_jobs = [
      cron(run_weekly_eval, weekday="sun", hour=2, minute=0),  # Sunday 02:00 UTC
  ]
  ```

### 13.5 Regression alert

- [ ] **13.5.1** Compare new EvalRun aggregate to previous EvalRun for the same `suite_name`. If `total_score` drops by > 10% → Slack webhook + audit log + Sentry breadcrumb.
- [ ] **13.5.2** Endpoint `GET /eval/runs/:id/regression` returns delta vs prior baseline.

### 13.6 Tests

- [ ] **13.6.1** `packages/agent/tests/test_eval_scorer.py`:
  - Cases-in-range, all-keywords-present → score 1.0.
  - Cases below min → structure_score = 0.
  - Partial keyword coverage → keyword_score = hits/total.
- [ ] **13.6.2** `packages/agent/tests/test_eval_runner.py` with `MockProvider` from M3 returning deterministic cases — assert FixtureScore stable across runs.
- [ ] **13.6.3** `apps/api/tests/test_eval_endpoints.py` — POST /eval/runs starts run, GET /eval/runs/:id returns completed result after BackgroundTasks finishes.

- [ ] **13.7** Commit: `feat(eval): harness backend + golden fixtures + weekly schedule (Closes #M4-8)`.

---

## Task 14: Cost dashboard UI

Per-workspace spend visualization + budget config.

### 14.1 Backend cost aggregation

- [ ] **14.1.1** Create `apps/api/src/suitest_api/services/cost_service.py`:
  ```python
  from datetime import date, timedelta
  from suitest_db.repositories.cost_aggregate_repo import CostAggregateRepo
  from suitest_db.repositories.agent_session_repo import AgentSessionRepo

  class CostService:
      def __init__(self, ca_repo: CostAggregateRepo, as_repo: AgentSessionRepo):
          self.ca, self.as_ = ca_repo, as_repo

      async def daily_rollup(self, workspace_id: str, on: date) -> None:
          """Aggregate AgentSession.cost_usd for `on` → cost_aggregates."""
          sessions = await self.as_.list_completed_on(workspace_id, on)
          buckets: dict[tuple[str, str, str], dict] = {}
          for s in sessions:
              key = (s.provider, s.model_id, s.kind)
              b = buckets.setdefault(key, {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "sessions": 0})
              b["tokens_in"] += s.tokens_in
              b["tokens_out"] += s.tokens_out
              b["cost_usd"] += float(s.cost_usd)
              b["sessions"] += 1
          for (prov, mod, kind), agg in buckets.items():
              await self.ca.upsert_daily(workspace_id=workspace_id, bucket_date=on,
                                         provider=prov, model_id=mod, kind=kind, **agg)

      async def query_range(self, workspace_id: str, since: date, until: date) -> list[dict]:
          return await self.ca.query_range(workspace_id, since, until)
  ```
- [ ] **14.1.2** ARQ cron `cost_daily_rollup` at 00:15 UTC daily — calls `daily_rollup` for each workspace with LLM enabled.
- [ ] **14.1.3** Endpoint `GET /cost/aggregate?since=<date>&until=<date>` returns time-series + breakdown.
- [ ] **14.1.4** Endpoint `GET/PUT /cost/budget` returns/updates `BudgetConfig` for workspace.

### 14.2 Frontend route

- [ ] **14.2.1** Create `apps/web/src/routes/_app/settings/billing.tsx` (TanStack Router):
  ```tsx
  import { createFileRoute } from "@tanstack/react-router";
  import { CostDashboard } from "@/components/cost/CostDashboard";
  import { Gated } from "@/components/gating/Gated";

  export const Route = createFileRoute("/_app/settings/billing")({
    component: () => (
      <Gated feature="ai_generation" fallback={<ZeroTierBillingHint />}>
        <CostDashboard />
      </Gated>
    ),
  });
  function ZeroTierBillingHint() {
    return <div className="p-6 text-fg-3">No LLM cost in ZERO tier. Switch to LOCAL or CLOUD to track spend.</div>;
  }
  ```
- [ ] **14.2.2** Add nav entry "Billing" under Settings sidebar group.

### 14.3 `<CostDashboard>` component

- [ ] **14.3.1** Create `apps/web/src/components/cost/CostDashboard.tsx`:
  - Period toggle: 7d / 30d (Tabs).
  - Headline cards: Total spend, Average per run, Sessions count.
  - Stacked BarChart (Recharts) by day × provider.
  - Breakdown table by provider × kind × model.
  - Budget config form (subcomponent).
- [ ] **14.3.2** Create `apps/web/src/components/cost/SpendByDayChart.tsx`:
  ```tsx
  import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, CartesianGrid, ResponsiveContainer } from "recharts";
  export function SpendByDayChart({ data, providers }: { data: Array<{date:string} & Record<string,number>>; providers: string[] }) {
    const colors = { anthropic: "#a78bfa", openai: "#4ade80", gemini: "#fbbf24", groq: "#f87171", ollama: "#737373" };
    return (
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
          <XAxis dataKey="date" stroke="#a3a3a3" />
          <YAxis tickFormatter={(v) => `$${v.toFixed(2)}`} stroke="#a3a3a3" />
          <Tooltip contentStyle={{ background: "#111", border: "1px solid #262626" }} />
          <Legend />
          {providers.map(p => <Bar key={p} dataKey={p} stackId="a" fill={(colors as any)[p] ?? "#737373"} />)}
        </BarChart>
      </ResponsiveContainer>
    );
  }
  ```
- [ ] **14.3.3** Create `apps/web/src/components/cost/BudgetConfigForm.tsx`:
  - Inputs: dailyCapUsd (number), softWarnPct (0–100), hardStop (toggle), slackWebhookUrl (text).
  - Save button → PUT /cost/budget; toast on success.

### 14.4 Threshold enforcement

- [ ] **14.4.1** Edit `packages/agent/src/suitest_agent/providers/litellm_router.py` — before each LLM call, check `BudgetConfig`:
  ```python
  async def acompletion(self, **kwargs):
      cfg = await self.budget_check.fetch(workspace_id)
      if cfg.hard_stop and (await self.spent_today(workspace_id) >= float(cfg.daily_cap_usd)):
          raise BudgetExceededError("BUDGET_EXCEEDED")
      result = await litellm.acompletion(**kwargs)
      cost = completion_cost(result)
      if (await self.spent_today(workspace_id) + cost) >= float(cfg.daily_cap_usd) * (cfg.soft_warn_pct / 100):
          await self._fire_slack_warn(cfg, ...)
      return result
  ```
- [ ] **14.4.2** Endpoint returning `429 BUDGET_EXCEEDED` if `hard_stop` triggers (handled by middleware mapping `BudgetExceededError`).

### 14.5 Tests

- [ ] **14.5.1** `apps/api/tests/test_cost_service.py` — daily rollup with 3 sessions across 2 providers → expect 2 cost_aggregate rows.
- [ ] **14.5.2** `apps/web/src/components/cost/__tests__/CostDashboard.test.tsx` (vitest + RTL) — renders headline numbers, period toggle switches.
- [ ] **14.5.3** Playwright E2E: navigate to /settings/billing, set budget to $1, save, verify toast + GET /cost/budget returns same value.

- [ ] **14.6** Commit: `feat(cost): dashboard UI + daily rollup + budget guard (Closes #M4-9)`.

---

## Task 15: Time-travel run replay UI

Read-only step-through of an agent session.

### 15.1 Backend replay endpoint (M3 should have this — verify and harden)

- [ ] **15.1.1** Verify `GET /agent/sessions/:id/replay` returns:
  ```json
  {
    "session_id": "as_xxx",
    "prompt_version": "v1.2",
    "model_id": "claude-sonnet-4-5",
    "seed": 42,
    "temperature": 0.2,
    "steps": [
      {
        "index": 0,
        "kind": "llm_call",
        "timestamp": "2026-05-26T10:00:00Z",
        "input_messages": [...],
        "output_message": {...},
        "tokens_in": 1023,
        "tokens_out": 87,
        "cost_usd": 0.012
      },
      {
        "index": 1,
        "kind": "tool_call",
        "tool_name": "playwright_screenshot",
        "args": {...},
        "result": {...},
        "artifact_urls": ["s3://..."]
      },
      ...
    ],
    "total_cost_usd": 0.075,
    "outcome": "completed"
  }
  ```
  If missing fields, add them as part of this task.

### 15.2 Frontend route + page

- [ ] **15.2.1** Create `apps/web/src/routes/_app/runs/$runId/replay.tsx`:
  ```tsx
  import { createFileRoute } from "@tanstack/react-router";
  import { ReplayViewer } from "@/components/runs/ReplayViewer";
  export const Route = createFileRoute("/_app/runs/$runId/replay")({
    component: ReplayPage,
  });
  function ReplayPage() {
    const { runId } = Route.useParams();
    return <ReplayViewer runId={runId} />;
  }
  ```

### 15.3 `<ReplayViewer>` component

- [ ] **15.3.1** Create `apps/web/src/components/runs/ReplayViewer.tsx`:
  ```tsx
  import { useQuery } from "@tanstack/react-query";
  import { useState, useEffect, useRef } from "react";
  import { TimelineScrubber } from "./TimelineScrubber";
  import { StepDetailPanel } from "./StepDetailPanel";
  import { ReplayControls } from "./ReplayControls";
  import { fetchReplay } from "@/lib/api-client";

  export function ReplayViewer({ runId }: { runId: string }) {
    const { data, isLoading } = useQuery({ queryKey: ["replay", runId], queryFn: () => fetchReplay(runId) });
    const [index, setIndex] = useState(0);
    const [playing, setPlaying] = useState(false);
    const timer = useRef<number | null>(null);

    useEffect(() => {
      if (!playing || !data) return;
      timer.current = window.setInterval(() => {
        setIndex(i => {
          if (i >= data.steps.length - 1) { setPlaying(false); return i; }
          return i + 1;
        });
      }, 1200);
      return () => { if (timer.current) window.clearInterval(timer.current); };
    }, [playing, data]);

    if (isLoading || !data) return <div>Loading replay…</div>;
    return (
      <div className="grid grid-rows-[auto_1fr_auto] h-full">
        <ReplayControls
          index={index} total={data.steps.length} playing={playing}
          onBack={() => setIndex(i => Math.max(0, i - 1))}
          onForward={() => setIndex(i => Math.min(data.steps.length - 1, i + 1))}
          onPlay={() => setPlaying(p => !p)}
        />
        <StepDetailPanel step={data.steps[index]} sessionMeta={{prompt_version: data.prompt_version, model_id: data.model_id}} />
        <TimelineScrubber steps={data.steps} index={index} onSelect={setIndex} />
      </div>
    );
  }
  ```

### 15.4 `<TimelineScrubber>`

- [ ] **15.4.1** Create `apps/web/src/components/runs/TimelineScrubber.tsx`:
  - Horizontal track with one tick per step.
  - Tick color by kind: violet=llm_call, accent=tool_call, amber=branch, red=error.
  - Click tick → onSelect(index).
  - Hover tick → tooltip with timestamp + summary.
  - Current index marker with red caret.

### 15.5 `<StepDetailPanel>`

- [ ] **15.5.1** Create `apps/web/src/components/runs/StepDetailPanel.tsx`:
  - Shows step kind, timestamp, tokens, cost.
  - LLM call: render input messages list + output message (markdown).
  - Tool call: render tool_name + args (JSON viewer) + result + screenshot if `artifact_urls` contains image.
  - If previous step has code or state, render Monaco diff (`@monaco-editor/react` DiffEditor) showing state delta between step N-1 and step N.

### 15.6 Diff viewer integration

- [ ] **15.6.1** Use `@monaco-editor/react` DiffEditor lazy-loaded (code-split via `React.lazy`) to avoid bundle bloat.
- [ ] **15.6.2** When step has `translated_code` (from action→code translation), show Monaco diff between `step.action` (left, plain text) and `step.translated_code` (right, language detected from MCP).

### 15.7 Tests

- [ ] **15.7.1** Vitest fixture-based: `apps/web/src/components/runs/__tests__/ReplayViewer.test.tsx`:
  - Mock fetchReplay with fixture session of 5 steps.
  - Render → step 0 visible.
  - Click forward → step 1 visible (StepDetailPanel content updated).
  - Click play → step advances every 1200ms (use vitest fake timers).
  - Click timeline tick 3 → step 3 visible.
- [ ] **15.7.2** Playwright E2E: open `/runs/<id>/replay`, click step-through, verify screenshot loads from MinIO.
- [ ] **15.7.3** a11y: keyboard navigation works (Tab → focus controls, Arrow keys → scrub timeline).

- [ ] **15.8** Commit: `feat(replay): time-travel run replay UI with timeline + diff (Closes #M4-10)`.

---

## Task 16: Observability — OpenTelemetry full wiring

### 16.1 Python SDK setup

- [ ] **16.1.1** Add to `apps/api/pyproject.toml`:
  ```toml
  observability = [
      "opentelemetry-distro>=0.48b0",
      "opentelemetry-exporter-otlp>=1.27.0",
      "opentelemetry-instrumentation-fastapi>=0.48b0",
      "opentelemetry-instrumentation-sqlalchemy>=0.48b0",
      "opentelemetry-instrumentation-httpx>=0.48b0",
      "opentelemetry-instrumentation-asyncpg>=0.48b0",
      "opentelemetry-instrumentation-redis>=0.48b0",
  ]
  ```
- [ ] **16.1.2** Create `apps/api/src/suitest_api/observability.py`:
  ```python
  from __future__ import annotations
  import os, logging
  from opentelemetry import trace
  from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION, DEPLOYMENT_ENVIRONMENT
  from opentelemetry.sdk.trace import TracerProvider
  from opentelemetry.sdk.trace.export import BatchSpanProcessor
  from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
  from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
  from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
  from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
  from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
  from opentelemetry.instrumentation.redis import RedisInstrumentor

  log = logging.getLogger(__name__)

  def setup_otel(app, engine) -> None:
      endpoint = os.environ.get("SUITEST_OTEL_ENDPOINT")
      if not endpoint:
          log.info("otel_disabled: SUITEST_OTEL_ENDPOINT not set")
          return
      resource = Resource.create({
          SERVICE_NAME: "suitest-api",
          SERVICE_VERSION: os.environ.get("SUITEST_VERSION", "dev"),
          DEPLOYMENT_ENVIRONMENT: os.environ.get("SUITEST_ENV", "production"),
      })
      provider = TracerProvider(resource=resource)
      provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
      trace.set_tracer_provider(provider)
      FastAPIInstrumentor.instrument_app(app, excluded_urls="health,ready,metrics")
      SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
      HTTPXClientInstrumentor().instrument()
      AsyncPGInstrumentor().instrument()
      RedisInstrumentor().instrument()
      log.info("otel_initialized", extra={"endpoint": endpoint})
  ```
- [ ] **16.1.3** Call `setup_otel(app, engine)` from `apps/api/src/suitest_api/main.py` lifespan startup.
- [ ] **16.1.4** Same setup in `apps/runner/src/suitest_runner/worker.py` with `SERVICE_NAME="suitest-runner"`.

### 16.2 Custom spans for agent + MCP

- [ ] **16.2.1** Edit `packages/agent/src/suitest_agent/graphs/generation.py` etc. — wrap each LangGraph node with `tracer.start_as_current_span("agent.node.<name>", attributes={...})`.
- [ ] **16.2.2** Edit `packages/mcp/src/suitest_mcp/client.py` — every `invoke_tool` call wrapped in span `mcp.invoke` with attrs `mcp.provider`, `mcp.tool_name`, `workspace_id`, `step.index`, `duration_ms`.
- [ ] **16.2.3** Edit `packages/agent/src/suitest_agent/providers/litellm_router.py` — wrap `acompletion` in span `llm.completion` with attrs `llm.provider`, `llm.model`, `llm.tokens_in`, `llm.tokens_out`, `llm.cost_usd`.

### 16.3 Sampling configuration

- [ ] **16.3.1** Support `SUITEST_OTEL_SAMPLE_RATIO` env (default 1.0 dev, 0.1 prod). Wire via `TraceIdRatioBased(ratio)` sampler.
- [ ] **16.3.2** Always-sample for `agent.session` root spans (long-tail debugging).

### 16.4 Frontend OTel (web)

- [ ] **16.4.1** Add to `apps/web/package.json`:
  ```json
  "@opentelemetry/api": "^1.9.0",
  "@opentelemetry/sdk-trace-web": "^1.27.0",
  "@opentelemetry/exporter-trace-otlp-http": "^0.54.0",
  "@opentelemetry/instrumentation-fetch": "^0.54.0",
  "@opentelemetry/instrumentation-xml-http-request": "^0.54.0"
  ```
- [ ] **16.4.2** Create `apps/web/src/lib/otel.ts`:
  ```ts
  import { WebTracerProvider } from "@opentelemetry/sdk-trace-web";
  import { BatchSpanProcessor } from "@opentelemetry/sdk-trace-base";
  import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
  import { registerInstrumentations } from "@opentelemetry/instrumentation";
  import { FetchInstrumentation } from "@opentelemetry/instrumentation-fetch";
  import { XMLHttpRequestInstrumentation } from "@opentelemetry/instrumentation-xml-http-request";
  import { Resource } from "@opentelemetry/resources";

  export function setupOtel() {
    const endpoint = (window as any).__SUITEST_OTEL_ENDPOINT__;
    if (!endpoint) return;
    const provider = new WebTracerProvider({ resource: new Resource({ "service.name": "suitest-web" }) });
    provider.addSpanProcessor(new BatchSpanProcessor(new OTLPTraceExporter({ url: endpoint })));
    provider.register();
    registerInstrumentations({
      instrumentations: [
        new FetchInstrumentation({ propagateTraceHeaderCorsUrls: [/.*/], ignoreUrls: [/\/health/, /\/metrics/] }),
        new XMLHttpRequestInstrumentation({ propagateTraceHeaderCorsUrls: [/.*/] }),
      ],
    });
  }
  ```
- [ ] **16.4.3** Wire `setupOtel()` in `apps/web/src/main.tsx` before `ReactDOM.createRoot`.

### 16.5 Tests

- [ ] **16.5.1** Pytest with in-memory exporter:
  ```python
  from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
  async def test_request_creates_spans(api_client, in_memory_otel):
      r = await api_client.get("/api/v1/capabilities")
      assert r.status_code == 200
      spans = in_memory_otel.get_finished_spans()
      names = {s.name for s in spans}
      assert "GET /api/v1/capabilities" in names
  ```
- [ ] **16.5.2** Vitest: verify `setupOtel()` no-ops when no endpoint configured.

- [ ] **16.6** Commit: `feat(otel): OpenTelemetry full instrumentation (Closes #M4-11)`.

---

## Task 17: Observability — Prometheus full metrics

### 17.1 Reuse instrumentator from M1a

- [ ] **17.1.1** Verify `apps/api/src/suitest_api/main.py` imports `prometheus_fastapi_instrumentator` and exposes `/metrics`. From M1a.
- [ ] **17.1.2** Verify runner exposes its own `/metrics` on port 8080.

### 17.2 Custom metrics module

- [ ] **17.2.1** Create `apps/api/src/suitest_api/metrics.py`:
  ```python
  from __future__ import annotations
  from prometheus_client import Counter, Histogram, Gauge

  suitest_runs_started_total = Counter(
      "suitest_runs_started_total", "Total runs started", ["workspace_id", "tier", "trigger"],
  )
  suitest_runs_duration_seconds = Histogram(
      "suitest_runs_duration_seconds", "Run duration in seconds",
      ["workspace_id", "tier", "outcome"],
      buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600),
  )
  suitest_agent_tokens_used_total = Counter(
      "suitest_agent_tokens_used_total", "Agent LLM tokens",
      ["workspace_id", "provider", "model_id", "kind", "direction"],  # direction: in|out
  )
  suitest_agent_cost_usd_total = Counter(
      "suitest_agent_cost_usd_total", "Agent LLM cost USD",
      ["workspace_id", "provider", "model_id", "kind"],
  )
  suitest_mcp_invocations_total = Counter(
      "suitest_mcp_invocations_total", "MCP tool invocations",
      ["workspace_id", "mcp_provider", "tool_name", "outcome"],
  )
  suitest_mcp_duration_seconds = Histogram(
      "suitest_mcp_duration_seconds", "MCP tool duration",
      ["workspace_id", "mcp_provider", "tool_name"],
      buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60),
  )
  suitest_defects_filed_total = Counter(
      "suitest_defects_filed_total", "Defects filed", ["workspace_id", "kind", "tracker"],
  )
  suitest_runs_queue_depth = Gauge(
      "suitest_runs_queue_depth", "Pending runs in queue", ["queue"],
  )
  suitest_eval_score = Gauge(
      "suitest_eval_score", "Latest eval score 0..1",
      ["workspace_id", "suite_name", "fixture_set"],
  )
  ```
- [ ] **17.2.2** Wire metric updates in:
  - `run_service.start` → `suitest_runs_started_total.inc(...)`.
  - `run_service.complete` → `suitest_runs_duration_seconds.observe(...)`.
  - `litellm_router.acompletion` → tokens + cost counters.
  - `mcp/client.invoke_tool` → invocations + duration.
  - `defect_service.create` → defects counter.
  - `runner/worker.before_job` → queue depth gauge from Redis LLEN.

### 17.3 ServiceMonitor (Helm)

- [ ] **17.3.1** Verify `templates/servicemonitor.yaml` from Task 6 picks up `app.kubernetes.io/component: api` AND `app.kubernetes.io/component: runner` labels.

### 17.4 Tests

- [ ] **17.4.1** `apps/api/tests/test_metrics.py`:
  - GET /metrics returns 200 + content-type `text/plain; version=0.0.4`.
  - Body contains `suitest_runs_started_total` and `suitest_agent_cost_usd_total`.
- [ ] **17.4.2** Trigger a fake run → assert counter incremented.

- [ ] **17.5** Commit: `feat(metrics): custom Prometheus metrics for runs/agent/mcp/defects (Closes #M4-11)`.

---

## Task 18: Observability — Sentry + Langfuse

### 18.1 Sentry SDK — api

- [ ] **18.1.1** Add `sentry-sdk[fastapi,sqlalchemy,httpx,asyncio]>=2.14` to `apps/api/pyproject.toml`.
- [ ] **18.1.2** Create `apps/api/src/suitest_api/sentry.py`:
  ```python
  import os, sentry_sdk
  from sentry_sdk.integrations.fastapi import FastApiIntegration
  from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
  from sentry_sdk.integrations.httpx import HttpxIntegration
  from sentry_sdk.integrations.asyncio import AsyncioIntegration

  def setup_sentry() -> None:
      dsn = os.environ.get("SUITEST_SENTRY_DSN")
      if not dsn:
          return
      sentry_sdk.init(
          dsn=dsn,
          environment=os.environ.get("SUITEST_ENV", "production"),
          release=os.environ.get("SUITEST_VERSION", "dev"),
          traces_sample_rate=float(os.environ.get("SUITEST_SENTRY_TRACES_SAMPLE_RATE", "0.1")),
          profiles_sample_rate=float(os.environ.get("SUITEST_SENTRY_PROFILES_SAMPLE_RATE", "0.0")),
          integrations=[
              FastApiIntegration(transaction_style="endpoint"),
              SqlalchemyIntegration(),
              HttpxIntegration(),
              AsyncioIntegration(),
          ],
          send_default_pii=False,
      )
  ```
- [ ] **18.1.3** Call `setup_sentry()` very early in `main.py` (before lifespan).

### 18.2 Sentry SDK — web

- [ ] **18.2.1** Add to `apps/web/package.json`: `"@sentry/react": "^8.30.0"`.
- [ ] **18.2.2** Create `apps/web/src/lib/sentry.ts`:
  ```ts
  import * as Sentry from "@sentry/react";
  export function setupSentry() {
    const dsn = (window as any).__SUITEST_SENTRY_DSN__;
    if (!dsn) return;
    Sentry.init({
      dsn,
      environment: (window as any).__SUITEST_ENV__ ?? "production",
      release: (window as any).__SUITEST_VERSION__ ?? "dev",
      integrations: [Sentry.browserTracingIntegration(), Sentry.replayIntegration({ maskAllText: true, blockAllMedia: true })],
      tracesSampleRate: 0.1,
      replaysSessionSampleRate: 0.0,
      replaysOnErrorSampleRate: 1.0,
      beforeSend(event) {
        // strip API keys from URL params
        if (event.request?.url) event.request.url = event.request.url.replace(/api_key=[^&]+/g, "api_key=[redacted]");
        return event;
      },
    });
  }
  ```
- [ ] **18.2.3** Wrap root component in `Sentry.ErrorBoundary` fallback in `apps/web/src/main.tsx`.

### 18.3 Langfuse integration

- [ ] **18.3.1** Add `langfuse>=2.50` to `apps/api/pyproject.toml` `observability` group.
- [ ] **18.3.2** Edit `packages/agent/src/suitest_agent/providers/litellm_router.py`:
  ```python
  import os
  import litellm
  def setup_langfuse() -> None:
      if not os.environ.get("LANGFUSE_HOST") or not os.environ.get("LANGFUSE_PUBLIC_KEY"):
          return
      litellm.success_callback = ["langfuse"]
      litellm.failure_callback = ["langfuse"]
  ```
  Call `setup_langfuse()` in `build_router()` init.
- [ ] **18.3.3** Pass `metadata={"workspace_id": ws, "session_id": sid, "tier": tier, "autonomy": auto}` on each completion call so Langfuse traces carry domain attrs.

### 18.4 Langfuse compose service (optional)

- [ ] **18.4.1** Edit `docker-compose.yml` to add `profiles: ["observability"]` service:
  ```yaml
    langfuse:
      image: langfuse/langfuse:2
      profiles: ["observability"]
      depends_on: [postgres]
      environment:
        DATABASE_URL: postgresql://suitest:${POSTGRES_PASSWORD}@postgres:5432/langfuse
        NEXTAUTH_SECRET: ${LANGFUSE_NEXTAUTH_SECRET:-changeme}
        NEXTAUTH_URL: http://localhost:3030
        SALT: ${LANGFUSE_SALT:-changeme}
      ports: ["3030:3000"]
  ```
- [ ] **18.4.2** Document: `docker compose --profile observability up -d` brings up Langfuse on 3030.

### 18.5 Langfuse Helm subchart

- [ ] **18.5.1** Add dependency in `Chart.yaml`:
  ```yaml
  - name: langfuse
    version: "0.x.x"
    repository: https://langfuse.github.io/langfuse-k8s
    condition: langfuse.enabled
  ```
- [ ] **18.5.2** Helm values pass-through in `values.yaml`:
  ```yaml
  langfuse:
    enabled: false
    nextauthSecret: ""
    salt: ""
    postgresql:
      enabled: false  # reuse Suitest's pg
  ```

### 18.6 Tests

- [ ] **18.6.1** `apps/api/tests/test_sentry_init.py` — with DSN env set, assert `sentry_sdk.Hub.current.client` not None.
- [ ] **18.6.2** `packages/agent/tests/test_langfuse_callback.py` — mock Langfuse server (httpserver), trigger LLM call (mock provider), assert POST to langfuse with trace metadata.

- [ ] **18.7** Commit: `feat(observability): Sentry + Langfuse integration (Closes #M4-11)`.

---

## Task 19: i18n English + Bahasa Indonesia

### 19.1 react-i18next setup

- [ ] **19.1.1** Add to `apps/web/package.json`:
  ```json
  "i18next": "^23.15.0",
  "react-i18next": "^15.0.0",
  "i18next-browser-languagedetector": "^8.0.0",
  "i18next-http-backend": "^2.6.0"
  ```
- [ ] **19.1.2** Create `apps/web/src/i18n/index.ts`:
  ```ts
  import i18n from "i18next";
  import { initReactI18next } from "react-i18next";
  import LanguageDetector from "i18next-browser-languagedetector";
  import HttpBackend from "i18next-http-backend";

  void i18n
    .use(HttpBackend)
    .use(LanguageDetector)
    .use(initReactI18next)
    .init({
      fallbackLng: "en",
      supportedLngs: ["en", "id"],
      ns: ["common", "dashboard", "cases", "runs", "settings", "errors"],
      defaultNS: "common",
      backend: { loadPath: "/locales/{{lng}}/{{ns}}.json" },
      detection: {
        order: ["localStorage", "navigator", "htmlTag"],
        lookupLocalStorage: "suitest.locale",
        caches: ["localStorage"],
      },
      interpolation: { escapeValue: false },
      returnNull: false,
    });

  export default i18n;
  ```
- [ ] **19.1.3** Wire in `apps/web/src/main.tsx` — `import "./i18n";` before `ReactDOM.createRoot`.

### 19.2 Locale files

- [ ] **19.2.1** Create `apps/web/public/locales/en/common.json`:
  ```json
  {
    "app_name": "Suitest",
    "tier_badge": "Tier: {{tier}}",
    "nav.dashboard": "Dashboard",
    "nav.cases": "Test Cases",
    "nav.runs": "Test Runs",
    "nav.defects": "Defects",
    "nav.analytics": "Analytics",
    "nav.traceability": "Traceability",
    "nav.integrations": "Integrations",
    "nav.settings": "Settings",
    "actions.create": "Create",
    "actions.cancel": "Cancel",
    "actions.save": "Save",
    "actions.delete": "Delete",
    "actions.run": "Run",
    "common.loading": "Loading…",
    "common.empty": "Nothing to show",
    "common.error": "Something went wrong"
  }
  ```
- [ ] **19.2.2** Create `apps/web/public/locales/id/common.json` (translated):
  ```json
  {
    "app_name": "Suitest",
    "tier_badge": "Tier: {{tier}}",
    "nav.dashboard": "Dasbor",
    "nav.cases": "Test Case",
    "nav.runs": "Run Test",
    "nav.defects": "Defect",
    "nav.analytics": "Analitik",
    "nav.traceability": "Traceability",
    "nav.integrations": "Integrasi",
    "nav.settings": "Pengaturan",
    "actions.create": "Buat",
    "actions.cancel": "Batal",
    "actions.save": "Simpan",
    "actions.delete": "Hapus",
    "actions.run": "Jalankan",
    "common.loading": "Memuat…",
    "common.empty": "Tidak ada data",
    "common.error": "Terjadi kesalahan"
  }
  ```
- [ ] **19.2.3** Create per-namespace files: `dashboard.json`, `cases.json`, `runs.json`, `settings.json`, `errors.json` in both `en/` and `id/`. Aim for ≥150 strings total covering all visible UI.

### 19.3 Wrap user-facing strings

- [ ] **19.3.1** Sweep `apps/web/src/components/` and `apps/web/src/routes/`:
  - Replace literal strings with `t("namespace.key")` via `useTranslation()`.
  - Lint rule `eslint-plugin-i18next` (`@suitest/eslint-config` add `i18next/no-literal-string` for `.tsx` files with allowlist for `Suitest`/`MCP`/etc.).
- [ ] **19.3.2** All errors mapped via `errors.json`:
  ```json
  {
    "LLM_DISABLED": "AI features are disabled in this tier. Switch to LOCAL or CLOUD.",
    "EMBEDDINGS_DISABLED": "Semantic search requires embeddings. Configure SUITEST_EMBEDDINGS_BACKEND.",
    "BUDGET_EXCEEDED": "Daily LLM budget exceeded.",
    "STEPS_REQUIRE_CODE_IN_ZERO_LLM": "This step has no code. ZERO tier needs explicit code or upgrade."
  }
  ```

### 19.4 Language switcher

- [ ] **19.4.1** Create `apps/web/src/components/shell/LocaleSwitcher.tsx`:
  ```tsx
  import { useTranslation } from "react-i18next";
  import { putMyLocale } from "@/lib/api-client";
  export function LocaleSwitcher() {
    const { i18n } = useTranslation();
    const change = async (lng: "en" | "id") => {
      await i18n.changeLanguage(lng);
      await putMyLocale(lng);  // persist on server
    };
    return (
      <div className="flex items-center gap-1">
        <button onClick={() => change("en")} className={i18n.language === "en" ? "font-semibold" : "text-fg-3"}>EN</button>
        <span className="text-fg-4">·</span>
        <button onClick={() => change("id")} className={i18n.language === "id" ? "font-semibold" : "text-fg-3"}>ID</button>
      </div>
    );
  }
  ```
- [ ] **19.4.2** Mount in user menu dropdown (`Topbar` / `UserMenu`).

### 19.5 Persist user preference

- [ ] **19.5.1** Endpoint `PUT /me/locale` accepts `{"locale": "en"|"id"}` → upsert `i18n_preferences`.
- [ ] **19.5.2** On login response include `user.locale`; web bootstraps `i18n.changeLanguage(user.locale)`.

### 19.6 Tests

- [ ] **19.6.1** Snapshot tests in vitest: render `<Sidebar>` with `i18n.changeLanguage("en")` and `("id")` — assert text differs and matches locale files.
- [ ] **19.6.2** Playwright E2E: switch language → reload → verify persistence.
- [ ] **19.6.3** Lint: `pnpm lint` fails if a `.tsx` introduces a non-allowlisted literal string.

- [ ] **19.7** Commit: `feat(i18n): English + Bahasa Indonesia (Closes #M4-12)`.

---

## Task 20: a11y audit pass

### 20.1 axe-core integration in Playwright

- [ ] **20.1.1** Add to `apps/web/package.json` devDeps: `"@axe-core/playwright": "^4.10.0"`.
- [ ] **20.1.2** Create `apps/web/tests/e2e/a11y.spec.ts`:
  ```ts
  import { test, expect } from "@playwright/test";
  import AxeBuilder from "@axe-core/playwright";

  const SCREENS = [
    { path: "/dashboard", name: "dashboard" },
    { path: "/cases", name: "cases-list" },
    { path: "/cases/c_login", name: "case-detail" },
    { path: "/runs", name: "runs-list" },
    { path: "/runs/r_smoke_1", name: "run-detail" },
    { path: "/runs/r_smoke_1/replay", name: "run-replay" },
    { path: "/defects", name: "defects" },
    { path: "/analytics", name: "analytics" },
    { path: "/traceability", name: "traceability" },
    { path: "/integrations", name: "integrations" },
    { path: "/settings/llm", name: "settings-llm" },
    { path: "/settings/automation", name: "settings-automation" },
    { path: "/settings/billing", name: "settings-billing" },
    { path: "/settings/mcp", name: "settings-mcp" },
  ];

  for (const s of SCREENS) {
    test(`a11y: ${s.name}`, async ({ page }) => {
      await page.goto(s.path);
      await page.waitForLoadState("networkidle");
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .disableRules(["color-contrast"])  // see Task 20.3
        .analyze();
      const critical = results.violations.filter(v => v.impact === "critical" || v.impact === "serious");
      expect(critical, JSON.stringify(critical.map(c => ({rule: c.id, nodes: c.nodes.length})), null, 2)).toEqual([]);
    });
  }
  ```

### 20.2 Fix common violations

- [ ] **20.2.1** Iterate Playwright runs locally; fix:
  - Missing alt text on images / icons (`aria-hidden="true"` for decorative).
  - Buttons without accessible name → add `aria-label`.
  - Form inputs without label → wrap in `<label>` or `aria-labelledby`.
  - Focus trap in modals — use `react-focus-lock` or `radix-ui` primitives (already wired in shadcn).
  - Keyboard nav for custom widgets (TimelineScrubber, Sidebar tree, ⌘K palette).

### 20.3 Color contrast pass

- [ ] **20.3.1** Re-enable `color-contrast` rule after auditing design tokens.
- [ ] **20.3.2** Verify `fg-3 #a3a3a3` on `bg-base #0a0a0a` passes WCAG AA (contrast ratio ≥ 4.5:1 for body text). Adjust if below.
- [ ] **20.3.3** `fg-4 #737373` should only be used for ≥18pt text (large-text 3:1 ratio); audit and replace where used as small body text.
- [ ] **20.3.4** Buttons / interactive — accent on bg-elev-1: verify ≥4.5:1.

### 20.4 ARIA roles + landmarks

- [ ] **20.4.1** Verify Topbar = `<header role="banner">`, Sidebar = `<nav aria-label="Main">`, main content = `<main>`, AI panel = `<aside aria-label="AI Assistant">`.
- [ ] **20.4.2** Skip-link `<a href="#main" class="sr-only focus:not-sr-only">Skip to main</a>` first child of `<body>`.

### 20.5 CI gate

- [ ] **20.5.1** Add Playwright a11y job to `.github/workflows/ci.yml`:
  ```yaml
  - name: a11y
    run: pnpm --filter @suitest/web exec playwright test tests/e2e/a11y.spec.ts
  ```
- [ ] **20.5.2** Block merge if critical/serious violations present.

- [ ] **20.6** Commit: `feat(a11y): axe-core CI gate + violation fixes (Closes #M4-13)`.

---

## Task 21: Documentation site — Astro Starlight

### 21.1 Initialize Starlight project

- [ ] **21.1.1** Create `docs/site/` directory. Run `pnpm create astro@latest docs/site -- --template starlight --typescript strict --no-install --no-git`.
- [ ] **21.1.2** Configure `docs/site/astro.config.mjs`:
  ```js
  import { defineConfig } from "astro/config";
  import starlight from "@astrojs/starlight";
  export default defineConfig({
    site: "https://suitest.dev",
    integrations: [
      starlight({
        title: "Suitest",
        logo: { src: "./src/assets/logo.svg" },
        social: { github: "https://github.com/suitest-dev/suitest" },
        editLink: { baseUrl: "https://github.com/suitest-dev/suitest/edit/main/docs/site/" },
        defaultLocale: "en",
        locales: {
          en: { label: "English" },
          id: { label: "Bahasa Indonesia" },
        },
        sidebar: [
          { label: "Getting Started", items: [
            { label: "Quickstart (compose)", link: "/start/compose" },
            { label: "Quickstart (helm)",    link: "/start/helm" },
            { label: "Concepts",             link: "/start/concepts" },
          ]},
          { label: "Deployment", items: [
            { label: "Docker Compose", link: "/deploy/compose" },
            { label: "Helm chart",     link: "/deploy/helm" },
            { label: "Air-gapped",     link: "/deploy/air-gapped" },
          ]},
          { label: "Concepts", items: [
            { label: "Capability tiers", link: "/concepts/tiers" },
            { label: "Autonomy levels",  link: "/concepts/autonomy" },
            { label: "MCP plugins",      link: "/concepts/mcp" },
            { label: "Generators",       link: "/concepts/generators" },
          ]},
          { label: "API Reference", autogenerate: { directory: "api" }},
          { label: "SDK", items: [
            { label: "Python (suitest-py)", link: "/sdk/python" },
            { label: "TypeScript (@suitest/sdk)", link: "/sdk/typescript" },
            { label: "CLI (suitest)", link: "/sdk/cli" },
          ]},
          { label: "Examples", autogenerate: { directory: "examples" }},
          { label: "Troubleshooting", link: "/troubleshoot" },
        ],
      }),
    ],
  });
  ```

### 21.2 Content pages

- [ ] **21.2.1** Write `docs/site/src/content/docs/start/compose.mdx` — full 5-minute quickstart with copy-paste blocks.
- [ ] **21.2.2** Write `docs/site/src/content/docs/start/helm.mdx` — production deploy walk.
- [ ] **21.2.3** Write `docs/site/src/content/docs/start/concepts.mdx` — overview of ZERO/LOCAL/CLOUD, MCP, generators.
- [ ] **21.2.4** Symlink (or include via remark plugin) `docs/CAPABILITY_TIERS.md`, `docs/AUTONOMY.md`, `docs/MCP_PLUGINS.md`, `docs/GENERATORS.md`, `docs/DEPLOYMENT.md` into Starlight content.
- [ ] **21.2.5** API reference: generated from `packages/shared/openapi.json` via `astro-openapi` or custom remark plugin → write to `docs/site/src/content/docs/api/`.

### 21.3 Versioning

- [ ] **21.3.1** Build per-tag deployment via GitHub Pages branches. Versioned URLs: `/v1.0/`, `/v1.1/`, `/latest/`.
- [ ] **21.3.2** `.github/workflows/docs-deploy.yml`:
  ```yaml
  name: docs-deploy
  on:
    push:
      tags: ["v*"]
      branches: ["main"]
  jobs:
    deploy:
      runs-on: ubuntu-latest
      permissions: { contents: read, pages: write, id-token: write }
      steps:
        - uses: actions/checkout@v4
        - uses: pnpm/action-setup@v4
        - uses: actions/setup-node@v4
          with: { node-version: '20' }
        - run: pnpm --filter @suitest/docs install
        - run: pnpm --filter @suitest/docs run build
        - uses: actions/upload-pages-artifact@v3
          with: { path: docs/site/dist }
        - uses: actions/deploy-pages@v4
  ```

### 21.4 Tests

- [ ] **21.4.1** `pnpm --filter @suitest/docs run build` green in CI.
- [ ] **21.4.2** Link-check via `lychee` action — fail on broken internal links.
- [ ] **21.4.3** Lighthouse on landing → score ≥ 95 perf/a11y/seo/best-practices.

- [ ] **21.5** Commit: `feat(docs): Astro Starlight documentation site (Closes #M4-14)`.

---

## Task 22: Example projects

### 22.1 `examples/playwright-e2e/`

- [ ] **22.1.1** Layout:
  ```
  examples/playwright-e2e/
  ├── README.md
  ├── playwright.config.ts          ← independent runnable test
  ├── tests/
  │   ├── login.spec.ts             ← Playwright spec exported from a Suitest case
  │   └── checkout.spec.ts
  ├── suitest/
  │   ├── suite.yaml                ← suite definition for import
  │   └── cases/
  │       ├── login.case.json
  │       └── checkout.case.json
  └── screenshots/
      └── run-detail.png            ← captured during build
  ```
- [ ] **22.1.2** README walks: import suite to Suitest → run → export back to Playwright → run standalone → verify identical results.

### 22.2 `examples/openapi-contract/`

- [ ] **22.2.1** Layout:
  ```
  examples/openapi-contract/
  ├── README.md
  ├── petstore.openapi.yaml         ← input spec
  ├── suitest/
  │   └── generated-suite.yaml      ← Suitest's deterministic generator output
  └── screenshots/
  ```
- [ ] **22.2.2** README: `suitest generate openapi --spec petstore.openapi.yaml` → produces contract suite → run → see results.

### 22.3 `examples/mixed-mcp-e2e/`

- [ ] **22.3.1** Reuse the M2 checkout demo — seed postgres → login api → checkout browser → verify api → verify db.
- [ ] **22.3.2** README references M2 demo, but as a standalone runnable example with self-contained docker-compose for the SUT (sample e-commerce backend).

### 22.4 `examples/air-gapped-deploy/`

- [ ] **22.4.1** Contents: `values-airgap.yaml`, `kind-airgap.yaml`, `README.md` with full air-gap drill walkthrough. Cross-references `docs/AIR_GAPPED.md`.
- [ ] **22.4.2** Optional `Tiltfile` for tilt dev loop.

### 22.5 Per-example quality bar

- [ ] **22.5.1** Each example: README ≥ 200 words, working config, screenshot, runs end-to-end in <5min on fresh laptop, dependencies pinned, license file (Apache 2.0 inherited).
- [ ] **22.5.2** CI job `.github/workflows/examples-smoke.yml` weekly runs each example in clean environment.

- [ ] **22.6** Commit per example: 4 commits total. Final: `docs(examples): 4 example projects (Closes #M4-15)`.

---

## Task 23: Dogfood — Suitest tests Suitest

### 23.1 Create the "Suitest Smoke" suite

- [ ] **23.1.1** Add suite to seed (extending M1a) OR create via API at CI startup. Suite name: `Suitest Smoke`. Workspace: dedicated `ws_dogfood`.
- [ ] **23.1.2** Cases (8 total):
  1. **Login flow** — POST /auth/login → assert 200 + token.
  2. **Capabilities probe** — GET /capabilities → assert tier matches env.
  3. **Create test case** — POST /test-cases with minimal body → assert 201 + id.
  4. **Trigger run** — POST /test-cases/:id/run → assert 202.
  5. **Watch SSE events** — GET /runs/:id/events → assert ≥3 events including `run.completed`.
  6. **Verify artifacts** — GET /runs/:id/artifacts → assert ≥1 artifact link with valid presigned URL.
  7. **Generate from own OpenAPI** — POST /generators/openapi with `specUrl=/openapi.json` → assert ≥10 cases generated.
  8. **Cleanup** — DELETE created cases.
- [ ] **23.1.3** Cases use `api-http-mcp` provider with `step.code` written in MCP HTTP action JSON.

### 23.2 CI workflow

- [ ] **23.2.1** Create `.github/workflows/dogfood-smoke.yml`:
  ```yaml
  name: dogfood-smoke
  on:
    schedule: [{ cron: "0 6 * * *" }]   # 06:00 UTC daily
    workflow_dispatch: {}
  jobs:
    smoke:
      runs-on: ubuntu-latest
      services:
        suitest:
          image: ghcr.io/suitest-dev/suitest-standalone:latest
          ports: ["8080:80"]
          env:
            DATABASE_URL: postgresql://suitest:pw@postgres:5432/suitest
            REDIS_URL: redis://redis:6379/0
        postgres:
          image: pgvector/pgvector:pg16
          env: { POSTGRES_USER: suitest, POSTGRES_PASSWORD: pw, POSTGRES_DB: suitest }
        redis:
          image: redis:7
      steps:
        - uses: actions/checkout@v4
        - uses: astral-sh/setup-uv@v3
        - run: uv pip install suitest
        - run: |
            until curl -sf http://localhost:8080/health; do sleep 2; done
        - run: suitest login --api-url http://localhost:8080 --token "${SMOKE_TOKEN}"
        - run: suitest run --suite "Suitest Smoke" --tag dogfood-nightly --follow
  ```

### 23.3 Staging environment

- [ ] **23.3.1** Provision `staging.suitest.dev` running latest `main` build (single-node k8s on small VM is fine for dogfood). Maintained via Helm + ArgoCD/Flux from `infra/k8s/staging/`.
- [ ] **23.3.2** Same workflow runs nightly against `staging.suitest.dev` (not local containers) — proves prod-like deploy works.

### 23.4 Failure handling

- [ ] **23.4.1** On smoke fail → open GitHub issue via `gh issue create --label dogfood-failure --title "[dogfood] smoke red {{ date }}"`.
- [ ] **23.4.2** Slack notification to #suitest-oncall.

- [ ] **23.5** Commit: `test(dogfood): Suitest tests Suitest smoke suite + nightly CI (Closes #M4-16)`.

---

## Task 24: License + community files

### 24.1 LICENSE

- [ ] **24.1.1** Create `/LICENSE` with the full Apache License 2.0 text (https://www.apache.org/licenses/LICENSE-2.0.txt). Year `2026`, copyright holder `Suitest Contributors`.

### 24.2 CONTRIBUTING.md

- [ ] **24.2.1** Create `/CONTRIBUTING.md`:
  ```markdown
  # Contributing to Suitest

  Thanks for your interest! Suitest is Apache-2.0 licensed and welcomes contributions.

  ## Quick start

  1. Fork + clone.
  2. `cp .env.example .env`
  3. `docker compose --profile zero up -d`
  4. Verify `localhost:8080`.
  5. `uv sync --all-extras` + `pnpm install`.

  ## Workflow

  - Branch per feature: `feat/<scope>-<short>`.
  - Conventional commits: `feat(api): add X (Closes #M4-7)`.
  - Each PR references one acceptance criterion.
  - CI must be green: ruff + mypy + pytest + tsc + vitest + helm-lint + a11y + Lighthouse.
  - One reviewer approval required.
  - Squash merge.

  ## Sign-off (DCO)

  All commits must be signed off:
      git commit -s -m "feat(api): foo"

  This certifies you have rights to contribute the code under Apache-2.0.

  ## Code style

  - Python 3.12 typed (mypy strict).
  - TypeScript strict.
  - No `Any` / `as any`.
  - No barrel files.

  ## Testing

  - TDD always: failing test → impl → green.
  - Backend: pytest. Frontend: vitest + Playwright.
  - Run `uv run pytest && pnpm test` locally before push.

  ## Reporting bugs / suggesting features

  See `.github/ISSUE_TEMPLATE/` and `SECURITY.md` for vulnerabilities.

  ## Code of Conduct

  See `CODE_OF_CONDUCT.md`.
  ```

### 24.3 CODE_OF_CONDUCT.md

- [ ] **24.3.1** Adopt Contributor Covenant 2.1: copy full text from https://www.contributor-covenant.org/version/2/1/code_of_conduct.txt. Replace contact email with `conduct@suitest.dev`.

### 24.4 SECURITY.md

- [ ] **24.4.1** Create `/SECURITY.md`:
  ```markdown
  # Security policy

  ## Supported versions

  | Version | Supported |
  |---------|-----------|
  | 1.0.x   | ✓         |
  | < 1.0   | ✗         |

  ## Reporting

  Email security@suitest.dev with PGP-encrypted message preferred.

  Public key fingerprint: <FINGERPRINT TBD>
  Key location: https://suitest.dev/.well-known/pgp-key.txt

  Response SLA:

  - Acknowledge: ≤ 72h
  - Triage + severity: ≤ 7d
  - Patch + advisory: ≤ 90d (sooner for criticals)

  ## Disclosure

  Coordinated disclosure preferred. We will credit reporters in CHANGELOG unless anonymity requested.

  ## Bug bounty

  Not currently funded; we welcome free responsible disclosure.
  ```

### 24.5 Issue templates

- [ ] **24.5.1** `.github/ISSUE_TEMPLATE/bug.yml`:
  ```yaml
  name: Bug report
  description: Report a defect in Suitest
  labels: [bug, triage]
  body:
    - type: input
      attributes: { label: Suitest version, description: 'e.g. v1.0.0' }
      validations: { required: true }
    - type: dropdown
      attributes:
        label: Tier
        options: [ZERO, LOCAL, CLOUD]
      validations: { required: true }
    - type: dropdown
      attributes:
        label: Deployment
        options: [docker-compose, standalone, helm]
      validations: { required: true }
    - type: textarea
      attributes: { label: What happened, description: Steps to reproduce, expected, actual }
      validations: { required: true }
    - type: textarea
      attributes: { label: Logs, render: shell }
  ```
- [ ] **24.5.2** `.github/ISSUE_TEMPLATE/feature.yml`:
  ```yaml
  name: Feature request
  description: Propose a new capability
  labels: [feature, triage]
  body:
    - type: textarea
      attributes: { label: Problem, description: What pain are you solving? }
      validations: { required: true }
    - type: textarea
      attributes: { label: Proposed solution }
    - type: dropdown
      attributes:
        label: Tier impact
        options: [ZERO only, LOCAL/CLOUD only, all tiers]
  ```
- [ ] **24.5.3** `.github/ISSUE_TEMPLATE/question.yml` — simple textarea with "Have you read the docs?" checkbox.

### 24.6 PR template

- [ ] **24.6.1** `.github/PULL_REQUEST_TEMPLATE.md`:
  ```markdown
  ## Summary

  Closes #<acceptance-criterion-id>

  ## Test plan

  - [ ] Backend tests added/updated
  - [ ] Frontend tests added/updated
  - [ ] Manual smoke
  - [ ] Documentation updated

  ## Capability gating

  - [ ] Endpoint(s) declare `Depends(require_tier(...))` if LLM-dependent
  - [ ] UI feature wrapped in `<Gated>` if LLM-dependent
  - [ ] ZERO tier still functional after this change

  ## Checklist

  - [ ] Conventional commit format
  - [ ] DCO sign-off (`git commit -s`)
  - [ ] CI green
  ```

### 24.7 Dependabot

- [ ] **24.7.1** `.github/dependabot.yml`:
  ```yaml
  version: 2
  updates:
    - package-ecosystem: "pip"
      directory: "/apps/api"
      schedule: { interval: "weekly", day: "monday" }
      open-pull-requests-limit: 5
      groups:
        otel: { patterns: ["opentelemetry-*"] }
        litellm: { patterns: ["litellm*"] }
    - package-ecosystem: "pip"
      directory: "/apps/runner"
      schedule: { interval: "weekly" }
    - package-ecosystem: "pip"
      directory: "/packages/agent"
      schedule: { interval: "weekly" }
    - package-ecosystem: "npm"
      directory: "/apps/web"
      schedule: { interval: "weekly" }
      groups:
        react: { patterns: ["react", "react-dom", "@types/react*"] }
        tanstack: { patterns: ["@tanstack/*"] }
        radix: { patterns: ["@radix-ui/*"] }
    - package-ecosystem: "github-actions"
      directory: "/"
      schedule: { interval: "weekly" }
    - package-ecosystem: "docker"
      directory: "/apps/api"
      schedule: { interval: "weekly" }
  ```

### 24.8 CODEOWNERS

- [ ] **24.8.1** `.github/CODEOWNERS`:
  ```
  *                              @suitest-dev/core
  apps/api/                      @suitest-dev/backend
  apps/runner/                   @suitest-dev/backend
  packages/agent/                @suitest-dev/ai
  packages/mcp/                  @suitest-dev/backend
  apps/web/                      @suitest-dev/frontend
  infra/                         @suitest-dev/platform
  docs/                          @suitest-dev/docs
  .github/                       @suitest-dev/core
  ```

- [ ] **24.9** Commit: `chore(community): LICENSE + CONTRIBUTING + COC + SECURITY + templates (Closes #M4-17)`.

---

## Task 25: Performance budgets

### 25.1 Frontend bundle budget

- [ ] **25.1.1** Add `vite-bundle-analyzer` to `apps/web/vite.config.ts`:
  ```ts
  import { visualizer } from "rollup-plugin-visualizer";
  export default defineConfig({
    plugins: [
      react(),
      visualizer({ filename: "dist/bundle-report.html", gzipSize: true, brotliSize: true }),
    ],
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            react: ["react", "react-dom"],
            tanstack: ["@tanstack/react-router", "@tanstack/react-query"],
            monaco: ["@monaco-editor/react", "monaco-editor"],
            recharts: ["recharts"],
          },
        },
      },
    },
  });
  ```
- [ ] **25.1.2** Add `bundlesize` config `apps/web/.bundlesize.json`:
  ```json
  [
    { "path": "./dist/assets/index-*.js", "maxSize": "200 kB", "compression": "gzip" },
    { "path": "./dist/assets/react-*.js", "maxSize": "60 kB", "compression": "gzip" },
    { "path": "./dist/assets/tanstack-*.js", "maxSize": "30 kB", "compression": "gzip" },
    { "path": "./dist/assets/monaco-*.js", "maxSize": "0 kB", "compression": "gzip" }
  ]
  ```
  Total target: < 350 KB gzipped for initial route.
- [ ] **25.1.3** CI step:
  ```yaml
  - name: Bundle size budget
    run: pnpm --filter @suitest/web run build && pnpm --filter @suitest/web exec bundlesize
  ```

### 25.2 Lighthouse CI gate

- [ ] **25.2.1** Verify `.github/workflows/ci.yml` already runs Lighthouse from M1b. Strengthen budgets:
  - Performance: ≥ 90
  - Accessibility: ≥ 95
  - Best Practices: ≥ 90
  - SEO: ≥ 90
  - TTI: < 1500ms (cold)
  - FCP: < 1000ms
  - LCP: < 2500ms
- [ ] **25.2.2** Run on `/dashboard`, `/cases`, `/runs/:id`, `/settings/billing`, `/runs/:id/replay`.

### 25.3 WebSocket latency

- [ ] **25.3.1** Synthetic monitor `tools/synthetic-ws-latency.py`:
  ```python
  import asyncio, time, statistics, websockets, json, sys
  async def main(ws_url: str, token: str):
      samples = []
      async with websockets.connect(f"{ws_url}?token={token}") as ws:
          for i in range(100):
              t0 = time.monotonic()
              await ws.send(json.dumps({"type": "ping", "id": i}))
              await ws.recv()
              samples.append((time.monotonic() - t0) * 1000)
      p50, p95, p99 = statistics.median(samples), sorted(samples)[95], sorted(samples)[99]
      print(f"p50={p50:.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms")
      if p95 > 500: sys.exit(f"WS p95 {p95:.1f}ms > 500ms budget")
  asyncio.run(main(sys.argv[1], sys.argv[2]))
  ```
- [ ] **25.3.2** Daily synthetic against `staging.suitest.dev`. Alert on p95 > 500ms or 3 consecutive failures.

### 25.4 DB query budget

- [ ] **25.4.1** Add `apps/api/src/suitest_api/middleware/slow_query.py`:
  ```python
  from sqlalchemy import event
  from sqlalchemy.engine import Engine
  import time, logging
  log = logging.getLogger(__name__)
  SLOW_THRESHOLD_MS = 200

  @event.listens_for(Engine, "before_cursor_execute")
  def before(conn, cursor, statement, params, context, executemany):
      context._query_start = time.monotonic()

  @event.listens_for(Engine, "after_cursor_execute")
  def after(conn, cursor, statement, params, context, executemany):
      dt = (time.monotonic() - context._query_start) * 1000
      if dt > SLOW_THRESHOLD_MS:
          log.warning("slow_query_p99", extra={"duration_ms": dt, "stmt_head": statement[:120]})
  ```
- [ ] **25.4.2** Pytest in `apps/api/tests/test_perf_budgets.py` — run typical workflow (list runs paginated, fetch one detail, fetch artifacts), assert no log warnings.

### 25.5 Tests

- [ ] **25.5.1** CI gate fails if bundle size, Lighthouse score, or WS p95 budgets breached.

- [ ] **25.6** Commit: `feat(perf): bundle/Lighthouse/WS/DB budgets enforced in CI (Closes #M4-3)`.

---

## Task 26: Scale + ops drills

### 26.1 Worker autoscale 2→8 validation

- [ ] **26.1.1** Drill script `tools/scale-drill.sh`:
  ```bash
  #!/usr/bin/env bash
  # Validate KEDA scales runner from 2 to 8 under load.
  set -euo pipefail
  NS=suitest
  kubectl scale deployment "$NS-runner" --replicas=2 -n "$NS"

  # Generate load: enqueue 200 fake runs over 30s
  for i in $(seq 1 200); do
    curl -fsSL -X POST "https://$STAGING_HOST/api/v1/runs/load-test" \
      -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
      -d '{"case_id": "c_smoke", "tag": "scale-drill"}' &
    sleep 0.15
  done
  wait

  # Watch replicas — should climb to 8
  for i in $(seq 1 30); do
    n=$(kubectl get deploy "$NS-runner" -n "$NS" -o jsonpath='{.status.readyReplicas}')
    echo "t=${i}0s replicas=$n"
    [ "$n" -ge 8 ] && { echo "PASS: scaled to $n"; exit 0; }
    sleep 10
  done
  echo "FAIL: did not scale to 8"; exit 1
  ```
- [ ] **26.1.2** Add `/api/v1/runs/load-test` endpoint (admin-only, returns immediately, enqueues fake job that sleeps 30s). Gated `require_role(ADMIN)` + `SUITEST_LOAD_TEST_ENABLED=1`.

### 26.2 Anthropic prompt caching

- [ ] **26.2.1** Edit `packages/agent/src/suitest_agent/providers/litellm_router.py` — when provider=anthropic, include `cache_control: {"type": "ephemeral"}` on the system+long context messages:
  ```python
  if self.provider == "anthropic" and msg["role"] == "system":
      msg = {**msg, "cache_control": {"type": "ephemeral"}}
  ```
- [ ] **26.2.2** Verify via Langfuse traces that subsequent identical sessions report `cache_read_input_tokens > 0`. Cost reduction ≈ 80% on cached prefix.
- [ ] **26.2.3** Document in `docs/AI_AGENT.md` §"Prompt caching" — enable conditions, observability path.

### 26.3 MinIO lifecycle for artifacts

- [ ] **26.3.1** Add `infra/minio/lifecycle-policy.json`:
  ```json
  {
    "Rules": [
      {
        "ID": "ArtifactsTransitionAfter90d",
        "Status": "Enabled",
        "Filter": { "Prefix": "artifacts/" },
        "Transitions": [{ "Days": 90, "StorageClass": "STANDARD_IA" }]
      },
      {
        "ID": "EvalRunArtifactsExpireAfter365d",
        "Status": "Enabled",
        "Filter": { "Prefix": "artifacts/eval/" },
        "Expiration": { "Days": 365 }
      }
    ]
  }
  ```
- [ ] **26.3.2** Apply via initContainer on MinIO statefulset OR `mc ilm import minio/suitest-runs < lifecycle-policy.json` as Helm post-install Job.

### 26.4 DB backup CronJob in Helm

- [ ] **26.4.1** Verify `infra/helm/suitest/templates/backup-cronjob.yaml` (from `docs/DEPLOYMENT.md` §4.1) exists. Add target bucket from `.Values.backup.targetUrl`. Default disabled (`.Values.backup.enabled: false`).
- [ ] **26.4.2** Test: `helm template --set backup.enabled=true` renders CronJob.

### 26.5 Restore drill

- [ ] **26.5.1** Document drill steps in `docs/RUNBOOK.md` §"Restore drill":
  1. Provision fresh k8s namespace.
  2. Restore postgres: `pg_restore --clean --if-exists -d $DATABASE_URL <dump>`.
  3. Restore MinIO via `mc mirror s3://remote-backup/ minio/local/`.
  4. Apply same `SUITEST_ENCRYPTION_KEY` Secret.
  5. Helm install same chart version as backup source.
  6. Smoke: GET /capabilities, login, open a run, verify artifact downloads.
  7. Smoke: run "Suitest Smoke" suite (Task 23) end-to-end.
- [ ] **26.5.2** Quarterly drill recorded in `docs/RUNBOOK.md` "Past drills" table.

- [ ] **26.6** Commit: `feat(ops): scale drill + prompt caching + lifecycle + backup (Closes #M4-3)`.

---

## Task 27: Status page + on-call runbook

### 27.1 Status page

- [ ] **27.1.1** Create `infra/statuspage/`. Choose homegrown for OSS (no SaaS dependency):
  - Static site (Astro) `infra/statuspage/`.
  - Heartbeat script `tools/heartbeat.sh` pings `/health`, `/ready`, `/metrics`, posts result to `status.json` in MinIO.
  - Site reads `status.json` and renders status grid.
- [ ] **27.1.2** GitHub Actions cron every 5min runs heartbeat against `staging.suitest.dev` AND `prod.suitest.dev`.
- [ ] **27.1.3** Status page deployed to GitHub Pages at `status.suitest.dev`.

### 27.2 Runbook

- [ ] **27.2.1** Create `docs/RUNBOOK.md`:
  ```markdown
  # Suitest operations runbook

  ## On-call rotation

  Rotation tracked in `.github/CODEOWNERS` + PagerDuty (community-funded).

  ## Common alerts

  ### `api_5xx_burst`

  Symptom: > 1% 5xx in 5min.

  1. Check Sentry: top error.
  2. Check Grafana panel `api` → DB connection pool exhaustion?
  3. Recent deploy? `helm rollback suitest <prev-rev>`.

  ### `runner_queue_depth`

  Symptom: `suitest_runs_queue_depth > 50` for 10min.

  1. Verify KEDA scaling: `kubectl get scaledobject -n suitest`.
  2. Manually scale: `kubectl scale deployment suitest-runner --replicas=8`.
  3. Check for stuck jobs: `kubectl logs -l app=suitest-runner | grep stuck`.

  ### `llm_provider_error_rate`

  Symptom: > 5% LLM API errors in 15min.

  1. Check provider status page (Anthropic, OpenAI, etc.).
  2. Check `LLMConfig.fallback_model` configured.
  3. Verify budget not exceeded: `suitest_agent_cost_usd_total` vs `BudgetConfig.daily_cap_usd`.

  ### `db_slow_query`

  Symptom: p99 query > 200ms.

  1. `kubectl exec deploy/suitest-postgres -- psql -c "SELECT * FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10"`.
  2. Missing index? Add via Alembic migration.

  ### `air_gap_egress_detected`

  Symptom: NetworkPolicy denied egress logs.

  1. Verify intent — should this pod egress?
  2. If yes, add to `networkPolicy.egress.allowLLMHosts` or `allowExternalIntegrations`.
  3. If no, audit + fix code path.

  ## Common procedures

  ### Rotate encryption key

  1. Generate new key: `openssl rand -base64 32`.
  2. Run rotation tool: `uv run python -m packages.db.scripts.rotate_encryption_key --new-key "$NEW_KEY"`.
  3. Update Secret + restart pods.

  ### LOCAL tier smoke

  See `docs/AIR_GAPPED.md` §"Verification checklist".

  ### Restore drill

  See Task 26.5 in plan-08.

  ### Past drills

  | Date | Type | Result | Notes |
  |------|------|--------|-------|
  | TBD  | air-gap | TBD | v1.0.0 launch |
  ```

- [ ] **27.3** Commit: `docs(runbook): on-call runbook + status page (Closes #M4-11)`.

---

## Task 28: Ship readiness — v1.0.0 tag

### 28.1 CHANGELOG

- [ ] **28.1.1** Create/update `/CHANGELOG.md`:
  ```markdown
  # Changelog

  All notable changes to Suitest. Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: [SemVer](https://semver.org/).

  ## [1.0.0] — 2026-05-26

  ### Added (M0–M4 highlights)

  - **M0** Monorepo scaffold: FastAPI + Vite + Postgres+pgvector + Redis + MinIO + Helm skeleton.
  - **M1a** Backend core: workspace-scoped REST, audit log, full seed (Nusantara Retail).
  - **M1b** Read-only UI: Dashboard, Cases, Runs, Defects, Analytics, Traceability, Integrations.
  - **M1c** MCP runner: registry, client, pool, 3 bundled (playwright, api, postgres), WebSocket logs, MinIO artifacts.
  - **M1d** TCM writes: case/suite CRUD, drag-reorder, bulk ops, rule-based defects, Jira/Linear/GitHub adapters, GitHub webhook trigger.
  - **M2** Generators + MCP expansion: OpenAPI/Recorder/Crawler generators, 5 additional bundled MCPs, custom MCP registration, mixed-MCP E2E, code export to Playwright/Cypress/Selenium.
  - **M3** CLOUD tier: LiteLLM router (9+ providers), AES-GCM `LLMConfig`, LangGraph 4 modes, versioned prompts, PRD/URL-semantic/MCP-discovery generators, action→code translate, AI diagnosis, assistant-ui chat, SSE token streaming, cost tracking, autonomy levels.
  - **M4** LOCAL tier + ship readiness:
    - Validated Ollama / llama.cpp / vLLM / LM Studio backends.
    - `fastembed` local embeddings (BAAI/bge-small, 384d) → free semantic search.
    - Helm chart production-grade (HPA via KEDA, PDB, NetworkPolicy default-deny, cert-manager Ingress).
    - Air-gapped k8s deploy validated.
    - `suitest-py` (PyPI) + `@suitest/sdk` (npm) + `suitest` CLI shipped.
    - Eval harness backend + 45 golden fixtures + weekly cron.
    - Cost dashboard UI + budget guard.
    - Time-travel run replay UI.
    - OpenTelemetry + Prometheus + Sentry + optional Langfuse.
    - i18n English + Bahasa Indonesia.
    - a11y axe-clean across all screens.
    - Astro Starlight docs site at suitest.dev.
    - 4 example projects.
    - Dogfood "Suitest Smoke" suite nightly.
    - Apache 2.0 LICENSE + community files.

  ### Security

  - All stored secrets AES-GCM encrypted via `packages/core/crypto`.
  - Default-deny NetworkPolicy in Helm.
  - DCO sign-off required.
  - PGP-signed release artifacts.

  ### Known limitations

  - Self-healing tests, visual regression with AI, mobile via Appium, desktop via computer-use — deferred to v2.x.
  - Multi-DB (MySQL/SQLite/Mongo) deferred to community demand.
  - SaaS hosted offering not provided; pure self-host.
  ```

### 28.2 README quickstart refresh

- [ ] **28.2.1** Update root `/README.md`:
  ```markdown
  <h1 align="center">Suitest</h1>
  <p align="center"><strong>MCP-native testing platform. Manual TCM, deterministic runs, autonomous AI when configured. Your stack, your LLM, your data.</strong></p>
  <p align="center">
    <a href="https://github.com/suitest-dev/suitest/actions"><img src="https://github.com/suitest-dev/suitest/actions/workflows/ci.yml/badge.svg"/></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg"/></a>
    <a href="https://pypi.org/project/suitest-py/"><img src="https://img.shields.io/pypi/v/suitest-py.svg"/></a>
    <a href="https://www.npmjs.com/package/@suitest/sdk"><img src="https://img.shields.io/npm/v/@suitest/sdk.svg"/></a>
  </p>

  ## Quickstart (5 minutes)

      git clone https://github.com/suitest-dev/suitest.git
      cd suitest
      cp .env.example .env
      docker compose --profile zero up -d
      docker compose exec api alembic upgrade head
      docker compose exec api python -m packages.db.seed
      open http://localhost:8080

  Login as `admin@example.com` / `changeme` (change immediately).

  ## Tiers

  - **ZERO** — no LLM. Manual TCM + deterministic runner + MCP plugins + rule-based defects.
  - **LOCAL** — local LLM (Ollama, llama.cpp, vLLM, LM Studio). Full AI in air-gap.
  - **CLOUD** — bring your own LLM key (9+ providers: Anthropic, OpenAI, Gemini, Groq, OpenRouter, Azure, Bedrock, Vertex, DeepSeek, …).

  See [`docs/CAPABILITY_TIERS.md`](docs/CAPABILITY_TIERS.md).

  ## Why Suitest

  - **MCP-native** — every step calls an MCP tool. Plug any MCP (Playwright, Postgres, GraphQL, K8s, custom).
  - **BYO LLM** — 100+ providers via LiteLLM. Local-only mode for privacy.
  - **Air-gap friendly** — full feature set with zero outbound network.
  - **Open source** — Apache 2.0, no vendor lock-in.

  ## SDKs

  - Python: `pip install suitest-py`
  - TypeScript: `pnpm add @suitest/sdk`
  - CLI: `pip install suitest`

  ## Docs

  Full docs: [suitest.dev](https://suitest.dev). Source: [`docs/`](docs/).

  ## Contributing

  See [`CONTRIBUTING.md`](CONTRIBUTING.md).

  ## License

  Apache 2.0. See [`LICENSE`](LICENSE).
  ```

### 28.3 Docs site landing

- [ ] **28.3.1** Update `docs/site/src/content/docs/index.mdx` to reflect v1.0 launch — feature pillars, screenshots, "Try in 5 min" CTA, comparison vs TestRail/Playwright/TestSprite.

### 28.4 Full smoke (manual + automated)

- [ ] **28.4.1** Manual checklist:
  - [ ] Fresh `docker compose up` in ZERO → all screens load.
  - [ ] Login → empty seed states → all CTAs lead to expected screens.
  - [ ] Full seed (`packages.db.seed`) → Dashboard populated.
  - [ ] Create case via UI → save → run → see WS log stream.
  - [ ] Defect created → file to Jira (mock backend) → row appears in Defects.
  - [ ] Switch tier to CLOUD with OpenAI key → AI panel visible → generate from PRD → cases drafted.
  - [ ] Switch tier to LOCAL with Ollama → same flow.
  - [ ] Switch to ZERO+fastembed → semantic search returns relevant cases.
  - [ ] Helm install on kind cluster → all pods Ready.
  - [ ] Air-gap drill (Task 9.3) passes.
- [ ] **28.4.2** Automated smoke: `tools/release-smoke.sh` runs all the above as Playwright + curl + helm scripts.

### 28.5 Tag v1.0.0

- [ ] **28.5.1** Run release prep script `tools/release.sh v1.0.0`:
  - `git checkout main && git pull`
  - Update versions in: root `package.json`, `apps/web/package.json`, `apps/api/pyproject.toml`, `packages/*/pyproject.toml`, `infra/helm/suitest/Chart.yaml`, `apps/cli/pyproject.toml`, `packages/sdk-py/pyproject.toml`, `packages/sdk-ts/package.json`.
  - Run `make openapi-snapshot` to regenerate `packages/shared/openapi.json` and commit.
  - Run `make sdk-py sdk-ts` regen.
  - Commit: `chore(release): v1.0.0`.
  - Tag `git tag -s v1.0.0 -m "v1.0.0 — Public OSS launch"` (GPG-signed).
  - Push tag → triggers release workflow.
- [ ] **28.5.2** Release workflow `.github/workflows/release.yml`:
  - Build images for api/runner/web/mcp-bundle → push to ghcr.io.
  - Build Helm chart → `helm push` to OCI registry.
  - Build air-gap bundle (Task 9.2) → upload as release asset.
  - Publish `suitest-py` to PyPI.
  - Publish `@suitest/sdk` to npm.
  - Publish `suitest` CLI to PyPI.
  - Generate GitHub Release with notes from CHANGELOG.

### 28.6 Announce

- [ ] **28.6.1** Draft HN post `docs/launch/hn-post.md`:
  ```markdown
  # Show HN: Suitest — MCP-native testing platform (Apache 2.0)

  We've been building Suitest, an OSS test case management + deterministic runner + AI features (when you bring an LLM key) all in one self-hostable Python/FastAPI + React app.

  Highlights:
  - MCP servers as the plugin layer (browser, API, postgres, graphql, k8s, custom)
  - 3-tier capability: ZERO (no LLM, ever) / LOCAL (Ollama/vLLM/llama.cpp/LM Studio) / CLOUD (9+ providers via LiteLLM)
  - Self-hostable: docker-compose laptop → Helm k8s production
  - Air-gapped friendly (zero egress validated)
  - SDK: Python + TypeScript + CLI
  - Eval harness, cost dashboard, time-travel replay UI

  Demo: https://suitest.dev/demo
  Docs: https://suitest.dev
  Code: https://github.com/suitest-dev/suitest

  We replaced our internal TestRail + Playwright + TestSprite stack with Suitest. Sharing it as Apache 2.0.

  Happy to answer questions.
  ```
- [ ] **28.6.2** Draft Reddit post for r/programming, r/devops, r/selfhosted.
- [ ] **28.6.3** Draft dev.to article: longer-form technical deep-dive.
- [ ] **28.6.4** Set up GitHub Discussions categories: Announcements, Q&A, Show and tell, Ideas.
- [ ] **28.6.5** Set up Discord server `suitest-community`, channels: #general, #help, #showcase, #plugins, #dev.
- [ ] **28.6.6** Add Discord + Discussions links to README + docs site footer.

- [ ] **28.7** Commit: `chore(release): tag v1.0.0 + launch materials (Closes #M4-17)`.

---

## Acceptance verification — M4 done definition

Run this checklist at end of M4:

- [ ] **M4-1** LOCAL tier — `docker compose --profile local up` with Ollama → AI panel works, generation produces structured cases. Same proof for llama.cpp, vLLM (via mock-backed test), LM Studio.
- [ ] **M4-2** ZERO + fastembed combo: `SUITEST_EMBEDDINGS_BACKEND=fastembed` + `SUITEST_LLM_PROVIDER=none` → `GET /search?semantic=1` returns relevant cases, latency < 500ms warmed-up.
- [ ] **M4-3** Helm `helm install` on kind cluster → all pods Ready, HPA scales runner under load, PDB enforced, NetworkPolicy default-deny logs zero unexpected allows.
- [ ] **M4-4** Air-gap drill: kind cluster with no public registry → suitest installs from local mirror → smoke green → tcpdump shows zero outbound packets to public IPs.
- [ ] **M4-5** `pip install suitest-py` works, quickstart example runs against staging, watch SSE iterator yields run events.
- [ ] **M4-5** `pnpm add @suitest/sdk` works, TS quickstart runs.
- [ ] **M4-7** `suitest --help` shows commands, `suitest run --suite smoke` works, `suitest replay <run-id>` opens browser.
- [ ] **M4-8** Eval `POST /eval/runs` → completes → score JSON returned. Weekly cron registered. 45 fixtures present (20+10+15).
- [ ] **M4-9** Settings → Billing page shows 7d/30d spend chart + breakdown table + budget config form. Hard-stop blocks LLM call with 429.
- [ ] **M4-10** `/runs/:id/replay` shows step-through timeline + Monaco diff. Play/pause/scrubber work.
- [ ] **M4-11** `/metrics` returns Prometheus format with custom metrics. OTel spans visible in Honeycomb/Tempo. Sentry receives test error. Langfuse traces LLM calls (when configured).
- [ ] **M4-12** Language switcher en/id works, persists. All visible UI strings translated.
- [ ] **M4-13** Playwright axe job green: zero critical/serious violations across 14 screens.
- [ ] **M4-14** Docs site at `suitest.dev` deploys, Lighthouse ≥95.
- [ ] **M4-15** 4 example projects each runnable end-to-end in <5 min on fresh laptop.
- [ ] **M4-16** Nightly dogfood smoke green for 7 consecutive days.
- [ ] **M4-17** `/LICENSE` Apache 2.0, all community files present, dependabot active, CODEOWNERS set, PR template enforced.
- [ ] **v1.0.0** tag pushed, GitHub Release with full notes + signed artifacts. PyPI + npm + helm + ghcr.io all published. HN/Reddit/dev.to drafts ready. Discord + Discussions live.

---

## Spec gaps + open questions surfaced during planning

These need confirmation before merging the PR that closes M4:

1. **Anthropic prompt caching cost reduction target** — design memo says ~80% reduction; this depends on prompt structure stability. Recommend Langfuse-based baseline measurement during Task 26.2 rather than asserting 80% as gate criterion.
2. **Air-gap LLM hosts FQDN egress** — vanilla NetworkPolicy uses CIDR not FQDN. Calico Enterprise / Cilium support FQDN egress. Document caveat: vanilla k8s air-gap users must either pin IPs (fragile) OR run egress gateway (e.g., HAProxy on stable IP). Air-gap with `tier=zero` sidesteps this entirely (recommended).
3. **LM Studio in container** — LM Studio desktop is not containerizable. Document use-case: dev laptop ↔ Docker via `host.docker.internal`. Production LOCAL tier should prefer Ollama/vLLM/llama.cpp.
4. **Eval fixture licensing** — fixtures contain mock PRDs/specs. Confirm all are CC0 or Apache 2.0 compatible before publish. No third-party PRDs without explicit permission.
5. **Status page hosting** — homegrown static at status.suitest.dev acceptable for v1.0. If outage takes down status page itself, consider hosting on different infra (Cloudflare Pages / GitHub Pages) — task currently uses GitHub Pages which is independent from production.
6. **Quarterly restore drill enforcement** — currently documented but not automated. Consider GitHub Issue auto-created every 90 days assigning drill owner.
7. **Bundle size <350KB target** — Monaco diff editor lazy-loaded (Task 15.6.1) is critical to hit budget; verify post-build report.
8. **Dogfood workspace data** — `ws_dogfood` is separate from seed `Nusantara Retail`. Ensure seed script supports both `--demo` (Nusantara) and `--dogfood` (smoke suite) flags.
9. **Sentry DSN management** — DSN is non-secret per Sentry docs, but treat as sensitive. Confirm community handling: pass as plain env in OSS distribution or require user-provided.
10. **Langfuse Helm subchart version** — Langfuse 3.x has breaking changes vs 2.x. Pin 2.x for v1.0 stability; upgrade in v1.x.

---

## Cross-references

- Capability tier matrix → [`docs/CAPABILITY_TIERS.md`](../../CAPABILITY_TIERS.md)
- Deployment topology → [`docs/DEPLOYMENT.md`](../../DEPLOYMENT.md)
- AI agent architecture → [`docs/AI_AGENT.md`](../../AI_AGENT.md)
- API contract → [`docs/API.md`](../../API.md)
- UI spec → [`docs/UI_SPEC.md`](../../UI_SPEC.md)
- Personas Lisa + Budi → [`docs/PRODUCT.md`](../../PRODUCT.md)
- Roadmap M4 acceptance → [`docs/ROADMAP.md`](../../ROADMAP.md) §M4
- Design memo → [`docs/superpowers/specs/2026-05-26-suitest-oss-pivot-design.md`](../specs/2026-05-26-suitest-oss-pivot-design.md)
- Prior milestone plans:
  - M0 → [`plan-01-m0-skeleton.md`](./2026-05-26-plan-01-m0-skeleton.md)
  - M1a → [`plan-02-m1a-backend-core.md`](./2026-05-26-plan-02-m1a-backend-core.md)
  - M1b → [`plan-03-m1b-frontend-readonly.md`](./2026-05-26-plan-03-m1b-frontend-readonly.md)
  - M1c → [`plan-04-m1c-runner-mcp.md`](./2026-05-26-plan-04-m1c-runner-mcp.md)
  - M1d → [`plan-05-m1d-tcm-writes.md`](./2026-05-26-plan-05-m1d-tcm-writes.md)
  - M2 → [`plan-06-m2-generators-mcp-expansion.md`](./2026-05-26-plan-06-m2-generators-mcp-expansion.md)
  - M3 → `plan-07-m3-llm-cloud-tier.md` (assumed; verify exists before starting M4)
