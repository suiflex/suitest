# docs/ARCHITECTURE.md

> Tech stack, services, dan deployment topology Suitest **OSS pivot** (Python/FastAPI, MCP-native, BYO LLM). Diff terhadap doc ini wajib kalau menambah/mengganti komponen. Single source of truth keputusan: [design memo](./superpowers/specs/2026-05-26-suitest-oss-pivot-design.md).

> ℹ️ **Built today:** `apps/api`, `apps/runner`, `apps/web`, `packages/db|mcp|core|shared`. `packages/agent` (LiteLLM + LangGraph) is a stub — targets M3. Eval CI job not built. See [ROADMAP.md](./ROADMAP.md).

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

Provider LLM bersifat **BYO** (Bring-Your-Own) — di-route via LiteLLM. Tier `ZERO` jalan tanpa container LLM sama sekali (resolver mematikan modul AI). Lihat [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md).

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
│   └── helm/         ← Helm chart `suitest/` untuk k8s
├── docs/             ← markdown specs (you are reading these)
├── pyproject.toml    ← uv workspace root
└── pnpm-workspace.yaml
```

**Kenapa monorepo:**
- Pydantic schemas di `packages/shared` di-import baik dari `api` maupun `runner` → kontrak konsisten.
- Atomic PR boleh menyentuh DB migration + endpoint + UI sekaligus.
- LangGraph & LiteLLM dipakai bersama oleh `api` (generation, conversation) dan `runner` (execution, diagnosis).

Frontend pakai pnpm; backend pakai `uv` (uv workspace, satu `pyproject.toml` root + per-package).

---

## 3. Service detail

### 3.1 `apps/web` — Frontend

| Aspek | Pilihan |
|-------|---------|
| Build | Vite 6 |
| Framework | React 19 + TypeScript 5.6 |
| Router | TanStack Router (file-based, type-safe) |
| Data fetching | TanStack Query (server state cache) |
| Styling | Tailwind 4 + `@layer base` design tokens (lihat `CLAUDE.md` §3.3) |
| UI primitives | shadcn/ui (Radix) — Dialog, Popover, Tooltip, Tabs |
| AI UI | `@ai-sdk/react` (streaming chat) + `assistant-ui` (tool render) |
| Forms | React Hook Form + Zod resolver |
| Realtime | Native `WebSocket` + `EventSource` (SSE) |
| State | Local: React state. Server: TanStack Query. App-wide (capabilities, autonomy, AI panel): Zustand |
| Auth | Bearer token (httpOnly cookie atau header), OAuth callback via API |
| Icons | Lucide React |
| Fonts | Geist Sans + Geist Mono (self-hosted, no external CDN — air-gap friendly) |

**Deploy:** static build (`pnpm --filter web build` → `dist/`), serve via nginx container.

### 3.2 `apps/api` — Backend

| Aspek | Pilihan |
|-------|---------|
| Framework | FastAPI 0.115 |
| ASGI server | Uvicorn (workers) di belakang nginx atau langsung |
| Schemas | Pydantic v2 (semua request/response model) |
| Auth | FastAPI-Users (session + Bearer JWT) + OAuth providers (Google, GitHub) |
| Authz | Hand-rolled `assert_can(user, action, resource)` policy module di `packages/core/authz.py` (roles: owner, admin, qa, viewer) |
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

**Deploy:** Docker image, 2+ replicas behind ingress. Lihat [DEPLOYMENT.md](./DEPLOYMENT.md).

### 3.3 `apps/runner` — Test executor

| Aspek | Detail |
|-------|--------|
| Type | ARQ worker (`arq.worker.Worker`), long-running async process |
| Concurrency | `max_jobs=8` per worker, autoscale 2–N (HPA queue-depth based) |
| MCP clients | `packages/mcp` — connect via stdio / SSE / WebSocket |
| Step engine | Decision tree per step (lihat [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md) §8) |
| Agentic step | Bila `step.code` kosong & tier != ZERO → translate via LangGraph node → MCP call |
| Output | Stream log lines ke Redis pub/sub channel `run:{id}` → `api` fan-out via WS/SSE |
| Artifacts | Upload ke MinIO/S3 (`s3://{bucket}/runs/{run_id}/{step_idx}/`) |
| Sandbox | Per-job temp workdir, cleaned up after success/fail |

**Deploy:** Docker image, HPA target `runner_queue_depth > 10` → scale up.

### 3.4 `packages/agent` — AI core

| Aspek | Detail |
|-------|--------|
| LLM router | **LiteLLM** — single client untuk 100+ provider (Anthropic, OpenAI, Gemini, Groq, Bedrock, Vertex, Ollama, llama.cpp, vLLM, LMStudio, OpenRouter, DeepSeek, Azure) |
| Orchestrator | **LangGraph** — state machine deterministik untuk 4 mode agen: `generation`, `execution`, `diagnosis`, `conversation` |
| Prompts | Versioned di `packages/agent/prompts/` — naming `v{N}/{task}.md`. `AgentSession.prompt_version` direkam ke DB |
| Capability gate | Setiap entrypoint dibungkus `@require_tier(min="LOCAL")` decorator — fail fast dgn `LLM_DISABLED` di ZERO |
| Autonomy gate | `@require_autonomy(min="assist")` decorator untuk operasi yang butuh auto-approve |
| Caching | LiteLLM cache (Redis) + provider-native prompt caching jika tersedia (Anthropic ephemeral, Gemini context) |
| Cost tracking | `litellm.completion_cost(response)` → `AgentSession.cost_usd` |
| Eval harness | `packages/agent/evals/` — golden cases + LangSmith-compatible runner (weekly CI job) |
| Observability | Optional Langfuse client — set `SUITEST_LANGFUSE_*` |

Lihat `docs/AI_AGENT.md` untuk detail per-mode.

### 3.5 `packages/db` — Database

PostgreSQL 16 + **pgvector** extension (single DB target untuk OSS v1.0).

- SQLAlchemy 2 (async) models di `packages/db/models/`
- Alembic migrations di `packages/db/alembic/versions/`
- Seed script `packages/db/seed.py` — bikin demo workspace "Nusantara Retail"
- pgvector index pakai `ivfflat` (default) atau `hnsw` (opt-in via setting)
- Vector dimensi flex per `SUITEST_EMBEDDINGS_BACKEND`: `fastembed=384`, `openai=1536`, `cohere=1024` (kolom `DocumentChunk.embedding` pakai `Vector(dim)` ditentukan saat migration `--embeddings-dim`)
- FTS fallback via `tsvector` kolom `DocumentChunk.search_tsv` — selalu aktif, termasuk ZERO tier

Schema lengkap: `docs/DATA_MODEL.md`.

### 3.6 `packages/mcp` — MCP plugin layer

| Aspek | Detail |
|-------|--------|
| SDK | `mcp` Python SDK (resmi Anthropic) |
| Transports | stdio, SSE, WebSocket — selectable per registered server |
| Registry | Static YAML di `packages/mcp/registry/default.yaml` (built-in providers) + DB table `mcp_provider` untuk user-added |
| Plugin loader | Lazy-instantiate client saat step pertama pakai provider, pooling per-workspace |
| Routing | `target_kind` (BE_REST / BE_GRAPHQL / FE_WEB / DATA / INFRA / CUSTOM) → default MCP provider, overridable per step |

Detail: [MCP_PLUGINS.md](./MCP_PLUGINS.md).

---

## 4. External integrations

| Service | Tujuan | SDK / Mekanisme |
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

Setiap integration tracker punya adapter di `apps/api/integrations/<vendor>.py` dengan interface uniform:

```python
class IssueTrackerAdapter(Protocol):
    async def create_issue(self, input: CreateIssueInput) -> Issue: ...
    async def update_issue(self, id: str, patch: UpdateIssueInput) -> Issue: ...
    async def link_external(self, issue_id: str, refs: list[ExternalRef]) -> None: ...
```

---

## 5. Environment variables

Naming: `SUITEST_<SCOPE>_<KEY>`. Defaults di `.env.example` = **ZERO tier**, jalan tanpa LLM.

**Required (semua tier):**

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
SUITEST_LLM_MODEL=                  # contoh: claude-sonnet-4-5, gpt-4o, ollama/llama3.1
SUITEST_LLM_BASE_URL=               # untuk self-hosted / OpenAI-compatible
SUITEST_EMBEDDINGS_BACKEND=none     # none | fastembed | openai | cohere
SUITEST_EMBEDDINGS_MODEL=
```

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

`.env.example` di-track; salin ke `.env` lokal, jangan commit. Production via Docker/Helm secret, **never** in repo.

---

## 6. Local development

```bash
# Sekali saja
uv sync                                # install Python deps untuk semua workspace package
pnpm install                           # install JS deps utk apps/web
cp .env.example .env                   # default ZERO tier
docker compose up -d postgres redis minio
uv run alembic -c packages/db/alembic.ini upgrade head
uv run python -m packages.db.seed

# Setiap hari
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

3 mode dukungan (compose / standalone / Helm). Detail step-by-step + `values.yaml` schema: [DEPLOYMENT.md](./DEPLOYMENT.md).

---

## 8. CI/CD

GitHub Actions workflows di `.github/workflows/`:

| Workflow | Trigger | Aksi |
|----------|---------|------|
| `lint.yml` | PR | `ruff check`, `ruff format --check`, `pnpm lint` |
| `typecheck.yml` | PR | `mypy packages apps`, `pnpm --filter web typecheck` (tsc) |
| `test.yml` | PR | `pytest -q` (api + runner + packages), `pnpm --filter web test` (vitest) |
| `e2e.yml` | PR | Run Suitest smoke suite (dogfood) di ZERO mode |
| `build-images.yml` | Push to `main` + tag | Build & push 3 image (`suitest-api`, `suitest-runner`, `suitest-web`) ke ghcr.io |
| `eval.yml` | Weekly cron | Run `packages/agent/evals/` against pinned provider matrix |
| `helm-release.yml` | Tag `v*` | Package + push chart ke OCI registry |

---

## 9. Observability

| Layer | Tool |
|-------|------|
| Tracing | OpenTelemetry SDK → OTLP exporter (Tempo / Jaeger / Honeycomb — user choice) |
| Logs | `structlog` JSON → stdout → container runtime aggregator |
| Metrics | `prometheus-fastapi-instrumentator` → `/metrics` endpoint |
| Errors | Sentry (web + api + runner) — opt-in via `SUITEST_SENTRY_DSN` |
| LLM trace | Langfuse self-host (opt-in) |
| Uptime | External (BetterStack / Uptime Kuma), ping `/health` tiap 30s |

**Custom metrics (Prometheus):**

- `suitest_runs_started_total{env,source,tier}`
- `suitest_runs_duration_seconds{outcome}`
- `suitest_runs_queue_depth` (gauge, dipakai HPA runner)
- `suitest_agent_generation_seconds{source,provider,model}`
- `suitest_agent_cost_usd_total{workspace,provider,model}`
- `suitest_mcp_session_starts_total{provider}`
- `suitest_mcp_call_seconds{provider,tool}`
- `suitest_defects_auto_filed_total{severity,tracker}`
- `suitest_capability_tier{tier}` (gauge labeled, 1 active)

---

## 10. Security

- TLS terminating di ingress (nginx / Traefik / cloud LB)
- Secrets via Docker secret / k8s Secret / external secret operator — **tidak pernah** di repo
- LLM API key disimpan **encrypted (AES-GCM, key derivation HKDF dari `SUITEST_ENCRYPTION_KEY`)** di `llm_config.api_key_ciphertext`
- Password user via FastAPI-Users (argon2 default)
- API token hashed (argon2) di DB
- WebSocket auth via Bearer token saat handshake (query param atau header)
- CSP header default: `default-src 'self'; img-src 'self' data:; connect-src 'self' <api_url> <ws_url>`
- Rate limit: `slowapi` per-IP + workspace-level limiter (per-tier multiplier)
- HMAC verification untuk inbound webhook (GitHub/GitLab/Jira) — secret per integration
- Audit log untuk: login, integration connect/disconnect, LLM config rotate, test case delete, defect close, autonomy change

---

## 11. Capability tier resolver

Implementasi di `packages/core/capabilities.py`. Algoritma:

1. Baca `SUITEST_LLM_PROVIDER` env saat process startup.
2. Map provider → tier:
   - `none` / unset → **ZERO**
   - `ollama` / `llamacpp` / `vllm` / `lmstudio` → **LOCAL**
   - lainnya (cloud SaaS) → **CLOUD**
3. Validate kombinasi (e.g. cloud provider butuh API key kecuali Bedrock/Vertex IAM).
4. Resolve `SUITEST_EMBEDDINGS_BACKEND` independen.
5. Cache hasil ke memory + expose via `GET /capabilities`.
6. Frontend fetch sekali saat boot, simpan di Zustand `useCapabilities()`.

Workspace-level override (lewat DB-stored `LLMConfig`) ditangani via reload signal — restart `api` + `runner` saat config berubah.

Spec lengkap: [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md).

---

## 12. Cara tambah dependency baru

| Stack | Tool | Cara |
|-------|------|------|
| Python | `uv` | `uv add <pkg>` di package yang relevan, commit `pyproject.toml` + `uv.lock` |
| Frontend | `pnpm` | `pnpm --filter web add <pkg>`, commit `package.json` + `pnpm-lock.yaml` |

PR requirement:

1. **Justify** di PR description: kenapa perlu, alternatif yang sudah dipertimbangkan, license check.
2. Update tabel di section 3 di doc ini bila dependency strategis (mis. ganti orchestrator).
3. Bundle size impact (frontend): `pnpm --filter web build && pnpm --filter web analyze`.
4. Approval dari maintainer — **auto-merge tidak boleh** untuk dependency baru.
5. Tambah entry di `docs/SECURITY.md` (TBD) bila dependency touch crypto / auth.

---

## 13. Referensi silang

- Tier spec → [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md)
- Deployment detail → [DEPLOYMENT.md](./DEPLOYMENT.md)
- Autonomy levels → [AUTONOMY.md](./AUTONOMY.md)
- MCP plugins → [MCP_PLUGINS.md](./MCP_PLUGINS.md)
- Generators → [GENERATORS.md](./GENERATORS.md)
- Design rationale → [design memo](./superpowers/specs/2026-05-26-suitest-oss-pivot-design.md)
