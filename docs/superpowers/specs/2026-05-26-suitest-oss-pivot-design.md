# 2026-05-26 — Suitest OSS Pivot Design Memo

> Konsolidasi keputusan dari sesi brainstorming 2026-05-26. Memo ini adalah single-source-of-truth untuk pivot Suitest dari proprietary Next.js/Fastify SaaS jadi self-hostable Python/FastAPI OSS dengan capability tiering, MCP-as-plugin, dan multi-provider LLM.

---

## 1. Tagline & positioning

> **MCP-native testing platform. Manual TCM, deterministic runs, autonomous AI when configured. Your stack, your LLM, your data.**

Posisi terhadap kompetitor:

| Capability | TestRail | Zephyr | Playwright | TestSprite | **Suitest ZERO** | **Suitest CLOUD** |
|------------|:--:|:--:|:--:|:--:|:--:|:--:|
| Manual TCM kelas-1 | ✓ | ✓ | ✗ | partial | ✓ | ✓ |
| Deterministic runner | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ |
| MCP plugin universal | ✗ | ✗ | ✗ | partial | ✓ | ✓ |
| AI generation | ✗ | beta | ✗ | ✓ | ✗ | ✓ |
| AI diagnose | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ |
| Self-host | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ |
| BYO LLM (100+ provider) | n/a | n/a | n/a | ✗ locked | n/a | ✓ |
| Air-gapped | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ (Ollama) |
| OSS | ✗ | ✗ | runner only | ✗ | ✓ | ✓ |

Suitest ZERO menggantikan TestRail+Playwright combined. Suitest CLOUD/LOCAL mengalahkan TestSprite.

---

## 2. Stack final

| Layer | Pilihan | Alasan |
|-------|---------|--------|
| Backend | Python 3.12 + FastAPI + Uvicorn + Pydantic v2 | LiteLLM, LangGraph, MCP Python SDK, browser-use native |
| Database | Postgres 16 + pgvector + SQLAlchemy 2 (async) + Alembic | Single DB target, mature, semua fitur perlu (FTS, JSON, vector) |
| LLM Router | LiteLLM | 100+ provider 1 client (OpenAI, Anthropic, Gemini, Bedrock, Vertex, Groq, DeepSeek, Ollama, OpenRouter, dll) |
| Agent orchestration | LangGraph | State machine deterministik utk 4 mode agen (generation/execution/diagnosis/conversation) |
| Embeddings | Pluggable: `none` / `fastembed` (local CPU) / cloud | Default `none` di ZERO, FTS fallback |
| Queue | ARQ (Redis async-native) | Ringan, native asyncio, kompatibel pola BullMQ |
| MCP | `mcp` Python SDK | Resmi Anthropic, multi-transport (stdio/SSE/WS) |
| Storage | MinIO (compose) / S3-compatible (helm) | OSS-friendly, ganti R2 |
| Auth | FastAPI-Users + OAuth (Google/GitHub) + Bearer token | Self-host friendly, multi-tenant |
| Frontend | Vite 6 + React 19 + TS + TanStack Router/Query + shadcn/ui + Tailwind 4 | Ekosistem AI UI matang, bundle ringan, SPA self-host |
| AI FE | `@ai-sdk/react` + `assistant-ui` | Streaming chat, tool render, provider-agnostic |
| Realtime | FastAPI WebSocket + SSE native | Built-in, no Socket.io needed |
| Observability | OpenTelemetry + Prometheus `/metrics` + Sentry | OSS-friendly self-host stack |
| LLM observability | Langfuse (self-host opsional) | Audit prompt/response, cost trace |
| Deploy | Dockerfile per service + docker-compose + Helm chart | Universal: laptop ↔ k8s |

---

## 3. Capability tiering

Diresolusi di startup dari env config. Cached, immutable per process.

```
SUITEST_LLM_PROVIDER = none | anthropic | openai | gemini | groq | openrouter | ollama | llamacpp | vllm | ...
SUITEST_LLM_API_KEY  = ...
SUITEST_EMBEDDINGS_BACKEND = none | fastembed | openai | cohere
```

| Tier | Trigger | AI features | Non-AI features |
|------|---------|-------------|-----------------|
| **ZERO** | provider=`none` atau unset | OFF | Full TCM, deterministic run, MCP plugins, webhook, traceability, analytics, defect filing (rule-based), 3 deterministic generators |
| **LOCAL** | provider ∈ {ollama, llamacpp, vllm, lmstudio} | Full, via local model | Full |
| **CLOUD** | provider ∈ {anthropic, openai, gemini, groq, openrouter, ...} | Full, via cloud | Full |

Capability resolution: lihat [CAPABILITY_TIERS.md](../CAPABILITY_TIERS.md).

---

## 4. Autonomy levels (per workspace)

Dial UX terpisah dari tier. Tier menentukan apa yg bisa, autonomy menentukan seberapa otomatis.

| Level | Default kapan | Generation | Execution | Diagnosis | Defect file |
|-------|---------------|------------|-----------|-----------|-------------|
| **manual** | ZERO tier forced; opt-in di CLOUD | OFF | manual run only | OFF | manual |
| **assist** | default saat LLM tersedia | AI → DRAFT, human approve setiap case | step.code dulu, fallback agentic w/ approval | AI diagnose → human review sebelum tutup | AI file, human override severity |
| **semi_auto** | opt-in | P2/P3 auto-approve, P0/P1 gated | full agentic, retry policy aktif | auto-categorize (FLAKE auto-rerun, REGRESSION block) | full auto |
| **auto** | opt-in (production CI) | semua auto-approve | full agentic + self-heal (v1.x) | full auto, auto-close FLAKE after N retries pass | full auto, auto-merge fix PR jika enabled |

Detail: lihat [AUTONOMY.md](../AUTONOMY.md).

---

## 5. MCP-as-plugin universal

MCP server jadi plugin layer utama. User pasang MCP apapun → Suitest pakai utk testing. Bukan cuma browser.

**Built-in routing default:**

| Target classification | MCP server default |
|-----------------------|--------------------|
| BE_REST (OpenAPI / Swagger) | `api-mcp` (HTTP client) |
| BE_GRAPHQL | `graphql-mcp` |
| BE_GRPC | `grpc-mcp` |
| FE_WEB | `browser-use-mcp` / `playwright-mcp` |
| FE_MOBILE | `appium-mcp` |
| DATA | `postgres-mcp` / `mongo-mcp` / `mysql-mcp` |
| INFRA | `kubernetes-mcp` |
| CUSTOM | user-provided MCP endpoint |

**Mixed-MCP test case** = single test punya step dgn `mcpProvider` berbeda-beda. Contoh checkout E2E: seed DB (postgres-mcp) → login (api-mcp) → checkout (playwright-mcp) → verify order (api-mcp) → verify DB state (postgres-mcp).

Detail: [MCP_PLUGINS.md](../MCP_PLUGINS.md).

---

## 6. Test generators

### Deterministic (jalan di semua tier termasuk ZERO)

1. **OpenAPI generator** — parse spec, generate per-operation: contract test, schema validate, required field, auth negative. Output `step.code` siap `mcp.api.request`.
2. **Browser Recorder** — user demo manual via Playwright/browser-use MCP → recorder capture DOM + network → output Playwright `step.code`.
3. **Heuristic URL crawler** — BFS depth-N, fill forms (Faker), klik tombol/link. Output skeleton smoke cases.

### LLM-driven (butuh CLOUD atau LOCAL)

4. **PRD natural language** — agen LLM ekstrak user story → drafting case + edge variants.
5. **URL semantic** — browser-use agentic crawl, paham intent ("checkout flow").
6. **MCP tool discovery** — connect ke custom MCP, LLM eksplorasi tool, generate test.
7. **Action→Code runtime translation** — saat run, step yg cuma punya `action` di-translate ke MCP call.

Classifier (deterministik, no LLM) auto-route input → target → MCP → generator. Lihat [GENERATORS.md](../GENERATORS.md).

---

## 7. Tier A fitur v1.0 (locked)

1. MCP-as-plugin universal
2. BYO LLM via LiteLLM
3. Hybrid manual+AI dgn DRAFT review (autonomy=assist default)
4. Air-gapped + Ollama support
5. Versioned prompts + run reproducibility
6. Test code export (Playwright/Cypress/Selenium target)
7. Deterministic generators (OpenAPI + Recorder + Heuristic crawler) — semua jalan di ZERO

---

## 8. Roadmap ringkas

- **M0** — Skeleton OSS (FastAPI + Vite + PG + Alembic + Docker compose), boot ZERO tier
- **M1** — Manual TCM full (CRUD case/suite, manual run dgn `step.code` via MCP, live log via WS, defect filing, traceability, analytics, integrations skeleton) — **ZERO mode end-to-end usable**
- **M2** — MCP plugin universal + 3 deterministic generators + multi-target step (mcp_provider per step)
- **M3** — LLM tier: LiteLLM + LangGraph + AI generation + AI diagnose + autonomy levels + Settings → LLM UI
- **M4** — LOCAL tier polish (Ollama, fastembed), test code export, eval harness, Helm chart, SDK + CLI public, dogfood

**v1.x (Tier B):** time-travel replay, eval harness UI, custom agent definition, diff-aware test selection, cost dashboard + budget guard, plugin SDK.

**v2.x (Tier C):** self-healing tests, visual regression dgn AI explanation, mobile via appium-mcp, desktop via computer-use MCP, multi-agent swarm (Planner/Executor/Critic), PR codegen patches.

Detail: [ROADMAP.md](../ROADMAP.md).

---

## 9. Konsekuensi data model

Tambahan kunci pada SQLAlchemy schema:

- `LLMConfig` — workspace-scoped, AES-GCM encrypted API key, provider + model preference
- `WorkspaceCapability` — materialized capability tier + autonomy level
- `Step.mcp_provider` (TEXT) + `Step.target_kind` (ENUM: BE_REST/BE_GRAPHQL/BE_GRPC/FE_WEB/FE_MOBILE/DATA/INFRA/CUSTOM)
- `Step.executable` (computed: `code IS NOT NULL OR (tier!=ZERO AND action IS NOT NULL)`)
- `AgentSession.prompt_version` + `AgentSession.model_id` + `AgentSession.seed` + `AgentSession.temperature` — reproducibility
- `AgentSession.cost_usd` — kalkulasi LiteLLM cost
- `DocumentChunk.embedding` — pgvector, dimensi sesuai backend (`fastembed`=384, `openai`=1536, `cohere`=1024)

Detail schema: [DATA_MODEL.md](../DATA_MODEL.md).

---

## 10. Konsekuensi API

- Tambah `GET /capabilities` public endpoint
- Tambah error code `LLM_DISABLED` (503) + `STEPS_REQUIRE_CODE_IN_ZERO_LLM` (400, optional saat workspace setting strict=true)
- `POST /agent/generate/cases` tambah `targetKind` (optional, classifier override)
- `POST /workspaces/:id/llm-config` — set/rotate LLM provider key
- `GET /workspaces/:id/autonomy` / `PUT` — autonomy level
- `GET /mcp/providers` — list MCP server terdaftar (default + user-added)
- `POST /mcp/providers` — register custom MCP server

Detail: [API.md](../API.md).

---

## 11. Konsekuensi UI

- App boot: `GET /capabilities` → Zustand `useCapabilities()` hook
- `<Gated feature="ai_generation">…</Gated>` wrapper komponen
- Tier badge di topbar (`ZERO` / `LOCAL · ollama:llama3.1` / `CLOUD · anthropic:claude-sonnet-4-5`)
- ZERO mode: AI panel hidden, generate button disabled w/ tooltip, banner di Dashboard
- Settings → LLM page (provider picker, key input write-only, test connection)
- Settings → Automation tab (autonomy level radio + per-feature override)
- Generation modal: step 1 "What are you testing?" (BE/FE/Data/Infra/Mixed) → step 2 source → step 3 MCP provider (auto-selected + override) → step 4 strategy
- MCP plugin browser page (Integrations → MCP Servers): install/test/configure

Detail: [UI_SPEC.md](../UI_SPEC.md).

---

## 12. Deployment topology

3 mode:

1. **Single-host docker-compose** — laptop / VPS, 1 file `docker-compose.yml`, profiles per tier
2. **Docker standalone** — single container all-in-one (api+web+worker) untuk hobbyist
3. **Helm chart** — k8s production, autoscale worker, separate web/api/runner pods

Default `.env` = ZERO tier. User edit untuk upgrade.

Detail: [DEPLOYMENT.md](../DEPLOYMENT.md).

---

## 13. Out of scope (anti-scope OSS v1.0)

- Multi-DB beyond Postgres (SQLite/MySQL/Mongo evaluated, ditolak utk v1.0 demi velocity)
- TypeScript backend (evaluated, ditolak demi LiteLLM + LangGraph ekosistem)
- Next.js SSR FE (ditolak demi SPA self-host friendliness)
- Mobile native app (web responsive saja)
- Performance/load testing built-in (pakai k6/Artillery separate, integration via webhook)
- Built-in security scanning (pakai Snyk separate)
- SaaS hosted version (pure self-host)

---

## 14. Open questions (defer ke implementation)

- AES-GCM key derivation strategi: env-based master vs KMS? → tentatif env-based, KMS opsional via Helm secret
- Multi-tenant queue isolation di ARQ: per-workspace queue name vs shared queue + filter? → tentatif shared queue, BullMQ-style priority
- MCP server discovery: static registry vs npx-style on-the-fly? → tentatif static registry di v1.0, dynamic v1.x
- Custom prompt fork per workspace: file-based vs DB? → tentatif file-based v1, DB v1.x

---

## 15. File audit (15 file)

Updated:
- `CLAUDE.md`
- `README.md`
- `docs/PRODUCT.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_MODEL.md`
- `docs/API.md`
- `docs/AI_AGENT.md`
- `docs/UI_SPEC.md`
- `docs/ROADMAP.md`

New:
- `docs/CAPABILITY_TIERS.md`
- `docs/DEPLOYMENT.md`
- `docs/MCP_PLUGINS.md`
- `docs/AUTONOMY.md`
- `docs/GENERATORS.md`
- `docs/superpowers/specs/2026-05-26-suitest-oss-pivot-design.md` (this memo)
