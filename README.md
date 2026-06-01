# Suitest

> **MCP-native testing platform. Manual TCM, deterministic runs, autonomous AI when configured. Your stack, your LLM, your data.**

Self-hostable OSS test platform — Python + FastAPI backend, Vite + React frontend, Postgres database, MCP plugin layer. Works fully without any LLM (ZERO tier). Plug in your own LLM key (cloud or local Ollama) to unlock AI generation, diagnosis, and conversational testing.

---

## What is Suitest

Suitest adalah platform untuk *manajemen, generasi, eksekusi, dan diagnosis* test case yang dirancang sekitar **MCP (Model Context Protocol)** sebagai universal adapter ke target apapun — backend REST, GraphQL, gRPC, frontend web/mobile, database, Kubernetes, atau custom MCP server kamu sendiri. Manual test case management berkualitas TestRail. Deterministic run engine sekelas Playwright + API tooling. Plus opsi *autonomous AI* yang bisa kamu nyalakan kapan pun dengan LLM key sendiri.

Posisi vs kompetitor: ZERO tier menggantikan **TestRail + Playwright** combined (tanpa lisensi). CLOUD/LOCAL tier melampaui **TestSprite** (tanpa vendor lock-in, tanpa kunci API mereka). Beda kunci dari semua: **tier-able** — kamu tidak harus pakai AI untuk dapat nilai, tapi kalau mau, kamu kontrol provider + cost + privacy. Lihat [design memo](./docs/superpowers/specs/2026-05-26-suitest-oss-pivot-design.md) untuk detail keputusan.

---

## 3-tier deployment

| Tier | Trigger | What you get | How to enable |
|------|---------|--------------|---------------|
| **ZERO** | `SUITEST_LLM_PROVIDER=none` (default) | Full TCM, deterministic runner via MCP, rule-based defect filing, traceability, analytics, 3 deterministic generators (OpenAPI / Recorder / Heuristic crawler), CI webhooks, Slack notifications, code export | Just `docker compose up` |
| **LOCAL** | `SUITEST_LLM_PROVIDER=ollama` (or `llamacpp` / `vllm` / `lmstudio`) | Everything ZERO has + AI generation from PRD/URL/MCP discovery, AI diagnosis, conversational test refinement, action→code runtime translation. All inference on your hardware. | Run Ollama, set env var, restart |
| **CLOUD** | `SUITEST_LLM_PROVIDER=anthropic` (or `openai`, `gemini`, `groq`, `openrouter`, `bedrock`, `vertex`, `deepseek`, ...) | Same as LOCAL but using cloud LLM with cost tracking + budget guard | Set provider + API key env vars |

100+ providers supported via [LiteLLM](https://docs.litellm.ai). Detail: [docs/CAPABILITY_TIERS.md](./docs/CAPABILITY_TIERS.md).

---

## Quick start (Docker Compose)

```bash
git clone https://github.com/<org>/suitest && cd suitest
cp .env.example .env
docker compose up -d
open http://localhost:3000
```

Login via Google OAuth — set `SUITEST_OAUTH_GOOGLE_CLIENT_ID` / `SUITEST_OAUTH_GOOGLE_CLIENT_SECRET` di `.env` sebelum `docker compose up`. M0 belum punya seed user; demo workspace (Nusantara Retail) + seed data datang di M1a. Default tier = **ZERO**.

**Untuk enable AI** (CLOUD tier dengan Anthropic):

```bash
# edit .env:
SUITEST_LLM_PROVIDER=anthropic
SUITEST_LLM_API_KEY=sk-ant-...
SUITEST_LLM_MODEL=claude-sonnet-4-5

docker compose restart api runner
```

Refresh browser → tier badge berubah jadi `CLOUD · anthropic:claude-sonnet-4-5`. AI panel + generate button aktif.

## Manual DoD smoke

See [docs/ROADMAP.md](docs/ROADMAP.md) M0 "Definition of done" for the
end-to-end clone → compose → login → dashboard smoke procedure.

**Untuk enable LOCAL tier dengan Ollama** (air-gapped friendly):

```bash
# edit .env:
SUITEST_LLM_PROVIDER=ollama
SUITEST_LLM_BASE_URL=http://ollama:11434
SUITEST_LLM_MODEL=llama3.1:8b

# pakai compose profile yang sudah include ollama service:
docker compose --profile local up -d
```

---

## Quick start (Helm / Kubernetes)

```bash
helm repo add suitest https://<org>.github.io/suitest-charts
helm install suitest suitest/suitest \
  --namespace suitest --create-namespace \
  --values values.yaml
```

Detail values + HA setup: [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md).

Air-gapped k8s deploy validated dengan Ollama in-cluster — lihat `examples/air-gapped-deploy/`.

---

## Repository structure

```
suitest/
├── README.md                ← kamu di sini
├── CLAUDE.md                ← coding rules untuk AI agent (Cursor/Claude Code)
├── Suitest.html             ← UI mockup (read-only, referensi visual; TEMPORARY — removed after M1b visual parity, source of truth = docs/UI_SPEC.md)
│
├── docs/
│   ├── PRODUCT.md           ← vision, personas, journeys, screen scope
│   ├── ARCHITECTURE.md      ← tech stack, service topology, deploy
│   ├── DATA_MODEL.md        ← SQLAlchemy schema + ER diagram
│   ├── API.md               ← REST endpoints + WebSocket events
│   ├── AI_AGENT.md          ← prompts, LangGraph state machines, tool registry
│   ├── UI_SPEC.md           ← per-screen component spec
│   ├── ROADMAP.md           ← milestones M0 → M15
│   ├── CAPABILITY_TIERS.md  ← ZERO/LOCAL/CLOUD resolution + gating rules
│   ├── MCP_PLUGINS.md       ← MCP registry, routing, sandbox security
│   ├── AUTONOMY.md          ← manual/assist/semi_auto/auto dial
│   ├── GENERATORS.md        ← deterministic + LLM-driven generator design
│   ├── DEPLOYMENT.md        ← compose + helm + air-gapped
│   ├── RUNBOOK.md           ← on-call playbook
│   └── superpowers/specs/   ← design memos (timestamped)
│
├── apps/
│   ├── web/                 ← Vite 6 + React 19 (Suitest UI)
│   ├── api/                 ← FastAPI backend
│   └── runner/              ← ARQ worker (per-step MCP dispatch)
│
├── packages/
│   ├── agent/               ← LiteLLM + LangGraph (4-mode agent)
│   ├── db/                  ← SQLAlchemy 2 async + Alembic
│   ├── mcp/                 ← MCP client + registry + pool
│   ├── shared/              ← cross-package Pydantic schemas
│   └── core/                ← capability resolver, autonomy, AES-GCM crypto
│
├── infra/
│   ├── docker/              ← Dockerfile per service
│   └── helm/suitest/        ← Helm chart
│
├── examples/                ← sample projects (playwright-e2e, openapi-contract, mixed-mcp-e2e, air-gapped-deploy)
└── eval/                    ← golden fixtures untuk eval harness
```

---

## Tech stack

| Layer | Tech | Why |
|-------|------|-----|
| Backend | Python 3.12 + FastAPI + Uvicorn + Pydantic v2 | LiteLLM + LangGraph + MCP Python SDK + browser-use native |
| Database | Postgres 16 + pgvector + SQLAlchemy 2 async + Alembic | Mature, FTS, JSON, vector — all in one DB |
| LLM Router | LiteLLM | 100+ provider via 1 client |
| Agent | LangGraph | Deterministic state machine per mode |
| Embeddings | Pluggable: `none` / `fastembed` / cloud | Default `none` di ZERO, FTS fallback |
| Queue | ARQ (Redis async) | Native asyncio, BullMQ-style ergonomics |
| MCP | `mcp` Python SDK (Anthropic) | Multi-transport: stdio, SSE, WebSocket |
| Storage | MinIO (compose) / S3-compatible (helm) | OSS-friendly |
| Auth | FastAPI-Users + OAuth (Google/GitHub) | Self-host friendly, multi-tenant |
| Frontend | Vite 6 + React 19 + TS + TanStack Router/Query + shadcn/ui + Tailwind 4 | Bundle ringan, SPA self-host |
| AI FE | `@ai-sdk/react` + `assistant-ui` | Streaming chat + tool render, provider-agnostic |
| Realtime | FastAPI WebSocket + SSE | Built-in, no Socket.io |
| Observability | OpenTelemetry + Prometheus + Sentry + (opsional) Langfuse | OSS self-host stack |
| Deploy | Docker + Compose + Helm | Universal: laptop → k8s |

Detail: [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md).

---

## Capability tiers explained

- **ZERO** — tier default. Tidak ada LLM call. Kamu dapat manual TCM, deterministic runner via MCP, defect filing rule-based, 3 deterministic generators (OpenAPI parser, browser recorder, heuristic URL crawler), traceability matrix, analytics, CI/CD webhooks, Slack/Jira/Linear/GitHub integrations. Setara TestRail+Playwright tanpa biaya lisensi.

- **LOCAL** — tier untuk privacy-first / air-gapped deploys. Jalankan Ollama (atau llamacpp / vLLM / LM Studio) di host/cluster yang sama. Dapat semua fitur AI tapi semua inference tetap di hardware kamu. Cocok untuk regulated industries (kesehatan, finance, defense, gov).

- **CLOUD** — tier untuk maximum capability dengan minimum ops. Bring your own LLM API key (Anthropic, OpenAI, Gemini, Groq, OpenRouter, dll). Dapat AI generation dari PRD/URL/MCP discovery, AI diagnosis, conversational test refinement, action→code runtime translation. Cost tracking per workspace + budget guard built-in.

Switch tier kapan pun via env var — no migration needed.

Detail: [docs/CAPABILITY_TIERS.md](./docs/CAPABILITY_TIERS.md).

---

## For AI coding agents (vibe coders)

Kalau kamu coding via Claude Code / Cursor / Cline:

1. **Baca [CLAUDE.md](./CLAUDE.md) dulu** — itu binding context untuk semua pekerjaan di repo ini.
2. **Baca [docs/PRODUCT.md](./docs/PRODUCT.md)** untuk konteks produk.
3. Pilih milestone di [docs/ROADMAP.md](./docs/ROADMAP.md), cross-reference ke:
   - [docs/UI_SPEC.md](./docs/UI_SPEC.md) untuk komponen frontend
   - [docs/API.md](./docs/API.md) untuk endpoint backend
   - [docs/DATA_MODEL.md](./docs/DATA_MODEL.md) untuk schema database
   - [docs/AI_AGENT.md](./docs/AI_AGENT.md) jika menyentuh agent / LLM
   - [docs/CAPABILITY_TIERS.md](./docs/CAPABILITY_TIERS.md) **wajib** sebelum implement fitur LLM-dependent
   - [docs/MCP_PLUGINS.md](./docs/MCP_PLUGINS.md) jika menyentuh runner / MCP

Heuristic kunci: **ZERO tier first**. Setiap fitur harus jalan deterministic dulu sebelum LLM enrichment ditambahkan.

---

## Documentation index

| Doc | Topic |
|-----|-------|
| [PRODUCT.md](./docs/PRODUCT.md) | Vision, personas, user journeys |
| [ARCHITECTURE.md](./docs/ARCHITECTURE.md) | Stack, services, topology |
| [DATA_MODEL.md](./docs/DATA_MODEL.md) | SQLAlchemy schema + entity diagram |
| [API.md](./docs/API.md) | REST + WebSocket contract |
| [AI_AGENT.md](./docs/AI_AGENT.md) | Prompts + LangGraph + tool registry |
| [UI_SPEC.md](./docs/UI_SPEC.md) | Per-screen component spec |
| [ROADMAP.md](./docs/ROADMAP.md) | M0 → M15 milestones |
| [CAPABILITY_TIERS.md](./docs/CAPABILITY_TIERS.md) | ZERO/LOCAL/CLOUD gating |
| [MCP_PLUGINS.md](./docs/MCP_PLUGINS.md) | MCP registry + sandbox security |
| [AUTONOMY.md](./docs/AUTONOMY.md) | Per-workspace autonomy dial |
| [GENERATORS.md](./docs/GENERATORS.md) | Generator design (deterministic + LLM) |
| [DEPLOYMENT.md](./docs/DEPLOYMENT.md) | Compose / Helm / air-gapped |
| [RUNBOOK.md](./docs/RUNBOOK.md) | On-call playbook |
| [Design memo 2026-05-26](./docs/superpowers/specs/2026-05-26-suitest-oss-pivot-design.md) | Pivot decisions source-of-truth |

---

## Comparison

| Capability | TestRail | Zephyr | Playwright | TestSprite | **Suitest ZERO** | **Suitest CLOUD** |
|------------|:--:|:--:|:--:|:--:|:--:|:--:|
| Manual TCM kelas-1 | ✓ | ✓ | ✗ | partial | ✓ | ✓ |
| Deterministic runner | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ |
| MCP plugin universal | ✗ | ✗ | ✗ | partial | ✓ | ✓ |
| AI generation | ✗ | beta | ✗ | ✓ | ✗ | ✓ |
| AI diagnosis | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ |
| Self-host | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ |
| BYO LLM (100+ provider) | n/a | n/a | n/a | ✗ locked | n/a | ✓ |
| Air-gapped | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ (Ollama) |
| OSS | ✗ | ✗ | runner only | ✗ | ✓ | ✓ |

---

## Roadmap

Public roadmap di [docs/ROADMAP.md](./docs/ROADMAP.md). Tiga fase:

- **v1.0** (M0 → M4) — Skeleton → ZERO mode E2E → MCP+generators → CLOUD tier → LOCAL polish + SDK + public launch
- **v1.x** (M5 → M9) — Tier B polish: time-travel & eval UI, diff-aware test selection, cost dashboard, custom agent definition, plugin SDK
- **v2.x** (M10 → M15) — Tier C agentic: self-healing tests, visual regression with AI explanation, mobile testing, desktop testing, multi-agent swarm, PR codegen patches

GitHub Projects board mirrors milestone state.

---

## Contributing

Lihat [CONTRIBUTING.md](./CONTRIBUTING.md) (akan ditambahkan di M4 launch prep) untuk:

- Dev environment setup
- Branch & PR conventions (conventional commits, one acceptance criterion per PR)
- Code style (ruff + mypy strict di Python, tsc strict + ESLint di TS)
- Testing requirements (pytest async + vitest + Playwright E2E)
- Sign-off (DCO)

Code of conduct: [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md). Security report: [SECURITY.md](./SECURITY.md).

---

## License

**Apache License 2.0** — permissive, OSS-friendly, hak komersialisasi user. Lihat [LICENSE](./LICENSE).

Catatan: AGPLv3 sempat dipertimbangkan untuk protection terhadap closed-source fork (terutama SaaS spin-off), tapi dipilih Apache 2.0 demi ekosistem OSS yang lebih luas dan friction lebih rendah untuk enterprise adoption. Keputusan final di [design memo](./docs/superpowers/specs/2026-05-26-suitest-oss-pivot-design.md).

---

## Acknowledgments

- **Anthropic** untuk [Model Context Protocol](https://modelcontextprotocol.io) — MCP adalah primary plugin layer Suitest
- **BerriAI** untuk [LiteLLM](https://github.com/BerriAI/litellm) — 100+ provider via 1 client interface
- **LangChain** untuk [LangGraph](https://langchain-ai.github.io/langgraph/) — deterministic agent state machines
- **Vercel** untuk [`@ai-sdk/react`](https://sdk.vercel.ai/docs) dan **assistant-ui** untuk komponen chat streaming
- **Shadcn** untuk komponen UI primitives
- **TanStack** untuk Router + Query
- **FastAPI** + **SQLAlchemy** + **Pydantic** maintainers

Dan semua design partners + early community contributors. 🎉
