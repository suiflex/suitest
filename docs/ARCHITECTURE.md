# docs/ARCHITECTURE.md

> Tech stack, services, and deployment topology for the Suitest **OSS pivot** (Python/FastAPI, MCP-native, BYO LLM). A diff against this doc is mandatory when adding/replacing components.

> ℹ️ **Built today:** `apps/api`, `apps/runner`, `apps/web`, `packages/db|mcp|core|shared`. `packages/agent` LLM foundation is built (M3-1..M3-5): LiteLLM provider layer (lazy-imported, ZERO-safe) + deterministic mock, LangGraph state machines for the 4 modes, versioned prompts + drift guard, `LLMConfig` API/UI + tier refresh. LLM-driven generators (M3-6..M3-9), runtime translation (M3-10), diagnosis wiring (M3-11), chat/streaming (M3-12/13), cost+autonomy (M3-14..16), and the eval CI job are not built yet. See [ROADMAP.md](./ROADMAP.md).

---

## 1. High-level topology

```
┌──────────────────────────────────────────────────────────────────────┐
│                       Browser (SPA, Vite/React)                      │
│                                                                      │
│   apps/web ─── HTTP REST ───┐         ┌─── WebSocket / SSE ────┐     │
└─────────────────────────────┼─────────┼──────────────────────────┘
                              ▼         ▼
                  ┌──────────────────────────────┐
                  │     apps/api (FastAPI)       │
                  │  • REST + Pydantic v2 schemas│
                  │  • WS / SSE gateway          │
                  │  • Auth (FastAPI-Users)      │
                  │  • Capability resolver       │
                  └──────────────┬───────────────┘
                                 │
   ┌────────────────┬────────────┼─────────────┬──────────────────┐
   ▼                ▼            ▼             ▼                  ▼
┌─────────┐  ┌─────────────┐ ┌──────────┐ ┌──────────┐  ┌──────────────────┐
│ Postgres│  │ Redis (ARQ  │ │ MinIO /  │ │  LLM     │  │  MCP server pool │
│ 16 +    │  │ queue+      │ │ S3       │ │  (BYO,   │  │  (browser-use,   │
│ pgvector│  │ pub/sub)    │ │ artifacts│ │  via     │  │   playwright,    │
│         │  │             │ │          │ │  LiteLLM)│  │   api-mcp, ...)  │
└─────────┘  └──────┬──────┘ └──────────┘ └────┬─────┘  └────────┬─────────┘
                    │                          │                 │
                    ▼                          │                 │
        ┌──────────────────────────┐           │                 │
        │  apps/runner (ARQ worker)│◀──────────┘                 │
        │  • dequeue run jobs      │                             │
        │  • execute step.code     │◀────────────────────────────┘
        │  • agentic translate via │   (MCP stdio / SSE / WS)
        │    packages/agent        │
        │  • stream logs via Redis │
        │    pub/sub → WS/SSE      │
        │  • upload artifacts→S3   │
        └──────────────────────────┘
```

The LLM provider is **BYO** (Bring-Your-Own) — routed via LiteLLM. The `ZERO` tier runs without any LLM container at all (the resolver disables the AI modules). See [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md).

---

## 2. Monorepo layout

```
suitest/
├── apps/
│   ├── web/          ← Vite 6 + React 19 + TS (SPA, no SSR)
│   ├── api/          ← FastAPI 0.115 + Uvicorn
│   └── runner/       ← ARQ worker, dequeues run jobs
├── packages/
│   ├── agent/        ← LiteLLM router + LangGraph orchestrator + capability/autonomy gates
│   ├── core/         ← capability resolver, autonomy resolver, shared domain logic
│   ├── db/           ← SQLAlchemy 2 (async) models + Alembic migrations + seed
│   ├── mcp/          ← MCP client wrapper, plugin registry, transport adapters
│   └── shared/       ← Pydantic v2 schemas, enums, error codes
├── infra/
│   ├── docker/       ← Dockerfile per service + supervisord cfg (standalone image)
│   └── helm/         ← Helm chart `suitest/` for k8s
├── docs/             ← markdown specs (you are reading these)
├── pyproject.toml    ← uv workspace root
└── pnpm-workspace.yaml
```

**Why a monorepo:**
- Pydantic schemas in `packages/shared` are imported by both `api` and `runner` → consistent contracts.
- An atomic PR may touch a DB migration + endpoint + UI at once.
- LangGraph & LiteLLM are shared by `api` (generation, conversation) and `runner` (execution, diagnosis).

The frontend uses pnpm; the backend uses `uv` (uv workspace, one root `pyproject.toml` + per-package).

---

## 3. Service detail

### 3.1 `apps/web` — Frontend

| Aspect | Choice |
|--------|--------|
| Build | Vite 6 |
| Framework | React 19 + TypeScript 5.6 |
| Router | TanStack Router (file-based, type-safe) |
| Data fetching | TanStack Query (server state cache) |
| Styling | Tailwind 4 + `@layer base` design tokens (see `CLAUDE.md` §3.3) |
| UI primitives | shadcn/ui (Radix) — Dialog, Popover, Tooltip, Tabs |
| AI UI | `@ai-sdk/react` (streaming chat) + `assistant-ui` (tool render) |
| Forms | React Hook Form + Zod resolver |
| Realtime | Native `WebSocket` + `EventSource` (SSE) |
| State | Local: React state. Server: TanStack Query. App-wide (capabilities, autonomy, AI panel): Zustand |
| Auth | Bearer token (httpOnly cookie or header), OAuth callback via API |
| Icons | Lucide React |
| Fonts | Geist Sans + Geist Mono (self-hosted, no external CDN — air-gap friendly) |

**Deploy:** static build (`pnpm --filter web build` → `dist/`), serve via nginx container.

### 3.2 `apps/api` — Backend

| Aspect | Choice |
|--------|--------|
| Framework | FastAPI 0.115 |
| ASGI server | Uvicorn (workers) behind nginx or directly |
| Schemas | Pydantic v2 (all request/response models) |
| Auth | FastAPI-Users (session + Bearer JWT) + OAuth providers (Google, GitHub) |
| Authz | Hand-rolled `assert_can(user, action, resource)` policy module in `packages/core/authz.py` (roles: owner, admin, qa, viewer) |
| Realtime | FastAPI native `WebSocket` + `EventSource` (SSE) — no Socket.io |
| Database | SQLAlchemy 2 async via `asyncpg`, sessions per-request |
| Queue producer | ARQ client (enqueue) |
| Rate limit | `slowapi` (per-IP) + custom workspace-level limiter |
| Observability | OpenTelemetry FastAPI instrumentation → OTLP exporter |
| Logging | `structlog`, JSON to stdout |
| Capability gate | `packages/core/capabilities.py` resolver — runs on startup, exposed via `GET /capabilities` |

**Routes mounted:**
- `/api/v1/*` — versioned REST
- `/capabilities` — public, returns tier + feature matrix
- `/health` — liveness probe
- `/ready` — readiness (checks DB, Redis, MinIO)
- `/metrics` — Prometheus scrape endpoint
- `/ws/runs/{id}` — WS upgrade for live run logs
- `/sse/runs/{id}` — SSE alternative (proxy-friendly)

**Deploy:** Docker image, 2+ replicas behind ingress. See [DEPLOYMENT.md](./DEPLOYMENT.md).

### 3.3 `apps/runner` — Test executor

| Aspect | Detail |
|--------|--------|
| Type | ARQ worker (`arq.worker.Worker`), long-running async process |
| Concurrency | `max_jobs=8` per worker, autoscale 2–N (HPA queue-depth based) |
| MCP clients | `packages/mcp` — connect via stdio / SSE / WebSocket |
| Step engine | Decision tree per step (see [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md) §8) |
| Agentic step | When `step.code` is empty & tier != ZERO → translate via LangGraph node → MCP call |
| Output | Stream log lines to Redis pub/sub channel `run:{id}` → `api` fan-out via WS/SSE |
| Artifacts | Upload to MinIO/S3 (`s3://{bucket}/runs/{run_id}/{step_idx}/`) |
| Sandbox | Per-job temp workdir, cleaned up after success/fail |

**Deploy:** Docker image, HPA target `runner_queue_depth > 10` → scale up.

### 3.4 `packages/agent` — AI core

| Aspect | Detail |
|--------|--------|
| LLM router | **LiteLLM** — single client for 100+ providers (Anthropic, OpenAI, Gemini, Groq, Bedrock, Vertex, Ollama, llama.cpp, vLLM, LMStudio, OpenRouter, DeepSeek, Azure) |
| Orchestrator | **LangGraph** — deterministic state machine for the 4 agent modes: `generation`, `execution`, `diagnosis`, `conversation` |
| Prompts | Versioned in `packages/agent/prompts/` — naming `v{N}/{task}.md`. `AgentSession.prompt_version` is recorded to the DB |
| Capability gate | Every entrypoint is wrapped in the `@require_tier(min="LOCAL")` decorator — fails fast with `LLM_DISABLED` on ZERO |
| Autonomy gate | `@require_autonomy(min="assist")` decorator for operations that require auto-approve |
| Caching | LiteLLM cache (Redis) + provider-native prompt caching where available (Anthropic ephemeral, Gemini context) |
| Cost tracking | `litellm.completion_cost(response)` → `AgentSession.cost_usd` |
| Eval harness | `packages/agent/evals/` — golden cases + LangSmith-compatible runner (weekly CI job) |
| Observability | Optional Langfuse client — set `SUITEST_LANGFUSE_*` |

See `docs/AI_AGENT.md` for per-mode details.

### 3.5 `packages/db` — Database

PostgreSQL 16 + **pgvector** extension (single DB target for OSS v1.0).

- SQLAlchemy 2 (async) models in `packages/db/models/`
- Alembic migrations in `packages/db/alembic/versions/`
- Seed script `packages/db/seed.py` — creates the demo workspace "Nusantara Retail"
- No persisted embeddings: the former `DocumentChunk.embedding` pgvector column was dropped in migration 0045 (RAG design superseded by the agent-first flow); the `SUITEST_EMBEDDINGS_BACKEND` env var and `--embeddings-dim` migration flag no longer exist. Semantic test-case search embeds on demand (no vectors stored).
- FTS fallback via the `tsvector` column `DocumentChunk.search_tsv` — always active, including on the ZERO tier

Full schema: `docs/DATA_MODEL.md`.

### 3.6 `packages/mcp` — MCP plugin layer

| Aspect | Detail |
|--------|--------|
| SDK | `mcp` Python SDK (official Anthropic) |
| Transports | stdio, SSE, WebSocket — selectable per registered server |
| Registry | Static YAML in `packages/mcp/registry/default.yaml` (built-in providers) + DB table `mcp_provider` for user-added ones |
| Plugin loader | Lazy-instantiate client when a step first uses a provider, per-workspace pooling |
| Routing | `target_kind` (BE_REST / BE_GRAPHQL / FE_WEB / DATA / INFRA / CUSTOM) → default MCP provider, overridable per step |

Details: [MCP_PLUGINS.md](./MCP_PLUGINS.md).

---

## 4. External integrations

| Service | Purpose | SDK / Mechanism |
|---------|--------|-----------------|
| LLM providers (any 100+) | LLM completion / embeddings | LiteLLM router |
| Jira Cloud | Issue tracker | REST API v3 (httpx) |
| Linear | Issue tracker | GraphQL via httpx |
| Slack | Notifications | Incoming webhook |
| GitHub | Webhooks + commits + App | `PyGithub` / httpx |
| GitLab | Webhooks | REST v4 via httpx |
| Browser-Use MCP | Browser automation | MCP stdio |
| Playwright MCP | Browser automation | MCP stdio |
| api-mcp / graphql-mcp / postgres-mcp / kubernetes-mcp | Built-in MCP servers | MCP stdio/SSE |
| Google OAuth | SSO | FastAPI-Users OAuth client |
| GitHub OAuth | SSO | FastAPI-Users OAuth client |

Every issue-tracker integration has an adapter in `apps/api/integrations/<vendor>.py` with a uniform interface:

```python
class IssueTrackerAdapter(Protocol):
    async def create_issue(self, input: CreateIssueInput) -> Issue: ...
    async def update_issue(self, id: str, patch: UpdateIssueInput) -> Issue: ...
    async def link_external(self, issue_id: str, refs: list[ExternalRef]) -> None: ...
```

---

## 5. Environment variables

Naming: `SUITEST_<SCOPE>_<KEY>`. Defaults in `.env.example` = **ZERO tier**, runs without an LLM.

**Required (all tiers):**

```env
DATABASE_URL=postgresql+asyncpg://suitest:suitest@postgres:5432/suitest
REDIS_URL=redis://redis:6379/0
SUITEST_AUTH_SECRET=<32-char random>
SUITEST_ENCRYPTION_KEY=<32-byte base64, AES-GCM master key>
SUITEST_WEB_URL=http://localhost:5173
SUITEST_API_URL=http://localhost:8000
SUITEST_S3_ENDPOINT=http://minio:9000
SUITEST_S3_BUCKET=suitest-runs
SUITEST_S3_ACCESS_KEY=minioadmin
SUITEST_S3_SECRET_KEY=minioadmin
```

**Tier dial (optional, default ZERO):**

```env
SUITEST_LLM_PROVIDER=none           # none | anthropic | openai | gemini | groq | openrouter |
                                    # ollama | llamacpp | vllm | lmstudio | azure | bedrock | vertex | deepseek
SUITEST_LLM_API_KEY=
SUITEST_LLM_MODEL=                  # example: claude-sonnet-4-5, gpt-4o, ollama/llama3.1
SUITEST_LLM_BASE_URL=               # for self-hosted / OpenAI-compatible
```

> `SUITEST_EMBEDDINGS_BACKEND` / `SUITEST_EMBEDDINGS_MODEL` no longer exist — persisted document embeddings were removed in migration 0045, and semantic test-case search embeds on demand (see CAPABILITY_TIERS.md §5).

**Optional per-integration:**

```env
SUITEST_JIRA_HOST=
SUITEST_JIRA_EMAIL=
SUITEST_JIRA_TOKEN=
SUITEST_LINEAR_API_KEY=
SUITEST_SLACK_WEBHOOK_URL=
SUITEST_GITHUB_APP_ID=
SUITEST_GITHUB_PRIVATE_KEY=
SUITEST_OAUTH_GOOGLE_CLIENT_ID=
SUITEST_OAUTH_GOOGLE_CLIENT_SECRET=
SUITEST_OAUTH_GITHUB_CLIENT_ID=
SUITEST_OAUTH_GITHUB_CLIENT_SECRET=
SUITEST_SENTRY_DSN=
SUITEST_LANGFUSE_PUBLIC_KEY=
SUITEST_LANGFUSE_SECRET_KEY=
SUITEST_LANGFUSE_HOST=
SUITEST_OTLP_ENDPOINT=
```

`.env.example` is tracked; copy it to a local `.env`, do not commit it. Production via Docker/Helm secrets, **never** in the repo.

---

## 6. Local development

```bash
# One-time setup
uv sync                                # install Python deps for all workspace packages
pnpm install                           # install JS deps for apps/web
cp .env.example .env                   # default ZERO tier
docker compose up -d postgres redis minio
uv run alembic -c packages/db/alembic.ini upgrade head
uv run python -m packages.db.seed

# Every day
uv run uvicorn apps.api.main:app --reload --port 8000 &
uv run arq apps.runner.worker.WorkerSettings &
pnpm --filter web dev                  # http://localhost:5173
```

Port mapping default:

| Service | Port |
|---------|------|
| web (Vite dev) | 5173 |
| api (Uvicorn) | 8000 |
| Postgres | 5432 |
| Redis | 6379 |
| MinIO API | 9000 |
| MinIO Console | 9001 |

---

## 7. Production deployment

3 supported modes (compose / standalone / Helm). Step-by-step details + `values.yaml` schema: [DEPLOYMENT.md](./DEPLOYMENT.md).

---

## 8. CI/CD

GitHub Actions workflows in `.github/workflows/`:

| Workflow | Trigger | Action |
|----------|---------|------|
| `lint.yml` | PR | `ruff check`, `ruff format --check`, `pnpm lint` |
| `typecheck.yml` | PR | `mypy packages apps`, `pnpm --filter web typecheck` (tsc) |
| `test.yml` | PR | `pytest -q` (api + runner + packages), `pnpm --filter web test` (vitest) |
| `e2e.yml` | PR | Run Suitest smoke suite (dogfood) in ZERO mode |
| `build-images.yml` | Push to `main` + tag | Build & push 3 images (`suitest-api`, `suitest-runner`, `suitest-web`) to ghcr.io |
| `eval.yml` | Weekly cron | Run `packages/agent/evals/` against pinned provider matrix |
| `helm-release.yml` | Tag `v*` | Package + push chart to OCI registry |

---

## 9. Observability

| Layer | Tool |
|-------|------|
| Tracing | OpenTelemetry SDK → OTLP exporter (Tempo / Jaeger / Honeycomb — user choice) |
| Logs | `structlog` JSON → stdout → container runtime aggregator |
| Metrics | `prometheus-fastapi-instrumentator` → `/metrics` endpoint |
| Errors | Sentry (web + api + runner) — opt-in via `SUITEST_SENTRY_DSN` |
| LLM trace | Langfuse self-host (opt-in) |
| Uptime | External (BetterStack / Uptime Kuma), ping `/health` every 30s |

**Custom metrics (Prometheus):**

- `suitest_runs_started_total{env,source,tier}`
- `suitest_runs_duration_seconds{outcome}`
- `suitest_runs_queue_depth` (gauge, used by the runner HPA)
- `suitest_agent_generation_seconds{source,provider,model}`
- `suitest_agent_cost_usd_total{workspace,provider,model}`
- `suitest_mcp_session_starts_total{provider}`
- `suitest_mcp_call_seconds{provider,tool}`
- `suitest_defects_auto_filed_total{severity,tracker}`
- `suitest_capability_tier{tier}` (gauge labeled, 1 active)

---

## 10. Security

- TLS terminated at the ingress (nginx / Traefik / cloud LB)
- Secrets via Docker secret / k8s Secret / external secret operator — **never** in the repo
- LLM API keys stored **encrypted (AES-GCM, HKDF key derivation from `SUITEST_ENCRYPTION_KEY`)** in `llm_config.api_key_ciphertext`
- User passwords via FastAPI-Users (argon2 default)
- API tokens hashed (argon2) in the DB
- WebSocket auth via Bearer token at handshake (query param or header)
- CSP header default: `default-src 'self'; img-src 'self' data:; connect-src 'self' <api_url> <ws_url>`
- Rate limit: `slowapi` per-IP + workspace-level limiter (per-tier multiplier)
- HMAC verification for inbound webhooks (GitHub/GitLab/Jira) — secret per integration
- Audit log for: login, integration connect/disconnect, LLM config rotate, test case delete, defect close, autonomy change

---

## 11. Capability tier resolver

Implemented in `packages/core/capabilities.py`. Algorithm:

1. Read the `SUITEST_LLM_PROVIDER` env at process startup.
2. Map provider → tier:
   - `none` / unset → **ZERO**
   - `ollama` / `llamacpp` / `vllm` / `lmstudio` → **LOCAL**
   - everything else (cloud SaaS) → **CLOUD**
3. Validate the combination (e.g. cloud providers require an API key, except Bedrock/Vertex IAM).
4. Cache the result in memory + expose it via `GET /capabilities`.
5. The frontend fetches once at boot, stores it in Zustand `useCapabilities()`.

> The former step "resolve `SUITEST_EMBEDDINGS_BACKEND` independently" is gone — that env var no longer exists (embeddings are no longer an env dial; see CAPABILITY_TIERS.md §5).

Workspace-level overrides (via DB-stored `LLMConfig`) are handled via a reload signal — restart `api` + `runner` when the config changes.

Full spec: [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md).

---

## 12. How to add a new dependency

| Stack | Tool | How |
|-------|------|-----|
| Python | `uv` | `uv add <pkg>` in the relevant package, commit `pyproject.toml` + `uv.lock` |
| Frontend | `pnpm` | `pnpm --filter web add <pkg>`, commit `package.json` + `pnpm-lock.yaml` |

PR requirement:

1. **Justify** in the PR description: why it is needed, alternatives already considered, license check.
2. Update the table in section 3 of this doc if the dependency is strategic (e.g. replacing the orchestrator).
3. Bundle size impact (frontend): `pnpm --filter web build && pnpm --filter web analyze`.
4. Approval from a maintainer — **auto-merge is not allowed** for new dependencies.
5. Add an entry in `docs/SECURITY.md` (TBD) if the dependency touches crypto / auth.

---

## 13. Cross-references

- Tier spec → [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md)
- Deployment detail → [DEPLOYMENT.md](./DEPLOYMENT.md)
- Autonomy levels → [AUTONOMY.md](./AUTONOMY.md)
- MCP plugins → [MCP_PLUGINS.md](./MCP_PLUGINS.md)
- Generators → [GENERATORS.md](./GENERATORS.md)
