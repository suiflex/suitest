# Suitest

> **MCP-native testing platform. Manual test management, deterministic runs, optional autonomous AI. Your stack, your LLM, your data.**

Self-hostable open-source test platform. Works fully **without any LLM** (ZERO tier) — manual test case management + a deterministic run engine that drives any target through [MCP](https://modelcontextprotocol.io) (Playwright, HTTP APIs, Postgres, and more). Plug in your own LLM key — cloud or local Ollama — to unlock AI generation, diagnosis, and conversational testing. No vendor lock-in, no forced API keys.

Backend: Python 3.12 + FastAPI · Frontend: Vite + React 19 · DB: Postgres 16 + pgvector · Queue: ARQ/Redis · Plugin layer: MCP.

---

## ⚠️ Project status

**Pre-v1.0, under active development.** What works **today** (milestones M0–M1e, tags `v0.1.0` → `v0.6.0`):

- ✅ Manual TCM — create/edit test cases, steps, suites, projects (read + write)
- ✅ Deterministic runner via MCP — `playwright`, `api-http`, `postgres` providers
- ✅ Live run logs (WebSocket), screenshots, MinIO artifacts, cancel/rerun
- ✅ Rule-based defects, traceability matrix, analytics, integrations + CI webhooks (GitHub/GitLab/Jira/Slack)
- ✅ Local auth: super-admin bootstrap + invite-only onboarding (no OAuth required)

**Roadmap (not built yet):** deterministic generators (M2, on branch `feat/m2-generators-mcp`), expanded MCP bundle + code export (M2), all AI/LLM features (M3+), SDK/CLI + public launch (M4). See [docs/ROADMAP.md](./docs/ROADMAP.md) — the single source of truth for build status.

> Every spec doc in `docs/` carries a build-status banner at the top (built vs. spec). Trust the banner before the prose.

---

## Quick start (Docker Compose)

```bash
git clone https://github.com/<org>/suitest && cd suitest
cp .env.example .env
```

Set a super-admin in `.env` so you can log in (ZERO tier needs no LLM):

```bash
SUITEST_AUTH_SECRET=<32-char-random-hex>     # openssl rand -hex 32
SUITEST_SUPERADMIN_EMAIL=admin@example.com
SUITEST_SUPERADMIN_PASSWORD=<strong-password>
```

```bash
docker compose up -d
open http://localhost:3000
```

Log in with the super-admin email/password. From **Settings → invite** others by link — onboarding is invite-only by default. Google OAuth is optional (set `SUITEST_OAUTH_GOOGLE_CLIENT_ID` / `_SECRET`). Default tier is **ZERO** — no LLM calls are ever made.

To load the demo workspace (Nusantara Retail + sample suites/cases/runs): `make seed` (or `docker compose exec api python -m suitest_db.seed`).

### Your first test — entirely from the UI, no LLM

From an empty install you can bootstrap and run a real browser test without touching the API:

1. **Log in** (super-admin email/password). A first **workspace** is created on install; the sidebar picker (`＋ New workspace`) makes more.
2. **Create a project, then a suite** — the Test Cases screen prompts you when each is empty.
3. **Author a test case** — “New case”, then add steps. A step targets an MCP provider (e.g. the bundled **`playwright-mcp`**, `target_kind = FE_WEB`) with a JSON tool call, e.g. `{"tool":"browser_navigate","arguments":{"url":"https://www.saucedemo.com"}}`.
4. **Run now** — the deterministic runner dispatches each step through MCP (Playwright drives a real browser) and the run-detail page **streams live status to PASS/FAIL**.
5. **Triage** — a failing step **auto-files a defect** (rule-based at ZERO); mark a suite **gating** to block deploys; watch pass-rate/readiness on the **dashboard**.

This whole journey is locked by a no-mock, real-backend Playwright suite — `make e2e-real` (boots a ZERO api + web + runner, seeds an empty workspace, and drives the UI against the live stack).

---

## Local development (no Docker for the app)

Prerequisites: **Python 3.12 + [uv](https://docs.astral.sh/uv/)**, **Node 20 + [pnpm](https://pnpm.io/)**, and Postgres/Redis/MinIO (easiest: `docker compose up -d postgres redis minio`).

```bash
make setup     # cp .env → install deps → run migrations → seed DB
make dev       # start API (:4000) + web (:3000) + runner together
```

Other useful targets (`make help` for the full list):

| Command | Does |
|---------|------|
| `make dev-api` / `dev-web` / `dev-runner` | Start one service |
| `make migrate` / `migrate-new m="..."` | Apply / create Alembic migration |
| `make seed` | Seed demo data |
| `make ci` | Everything CI runs: lint + typecheck + tests (py + web) |
| `make check-all` | Lint + typecheck only (no tests) |
| `make docker-up-local` / `docker-up-cloud` | Boot with Ollama / cloud-LLM profile |

---

## Enable AI (optional)

AI features are **roadmap (M3+)** and not active yet, but the tier switch is wired. Switch tiers any time via env var — no migration needed.

**CLOUD** (bring your own key — 100+ providers via [LiteLLM](https://docs.litellm.ai)):

```bash
SUITEST_LLM_PROVIDER=anthropic        # or openai, gemini, groq, openrouter, bedrock, ...
SUITEST_LLM_API_KEY=sk-ant-...
SUITEST_LLM_MODEL=claude-sonnet-4-5
docker compose restart api runner
```

**LOCAL** (privacy-first / air-gapped, all inference on your hardware):

```bash
SUITEST_LLM_PROVIDER=ollama
SUITEST_LLM_BASE_URL=http://ollama:11434
SUITEST_LLM_MODEL=llama3.1:8b
docker compose --profile local up -d   # includes an Ollama service
```

---

## Capability tiers

| Tier | Trigger | What you get |
|------|---------|--------------|
| **ZERO** | `SUITEST_LLM_PROVIDER` empty (default) | Full manual TCM, deterministic runner via MCP, rule-based defects, traceability, analytics, integrations + CI webhooks. No LLM call ever. |
| **LOCAL** | `ollama` / `llamacpp` / `vllm` / `lmstudio` | Everything ZERO has + AI features *(roadmap M3)*, all inference on your hardware. |
| **CLOUD** | `anthropic` / `openai` / `gemini` / ... | Same as LOCAL using a cloud LLM, with cost tracking + budget guard *(roadmap M3)*. |

Detail: [docs/CAPABILITY_TIERS.md](./docs/CAPABILITY_TIERS.md).

---

## Repository structure

```
suitest/
├── README.md                ← you are here
├── CLAUDE.md                ← coding rules for AI agents (Cursor / Claude Code)
├── Suitest.html             ← UI mockup (read-only; removed after M1b visual parity)
├── Makefile                 ← all dev commands (make help)
│
├── apps/
│   ├── web/                 ← Vite 6 + React 19 (Suitest UI)
│   ├── api/                 ← FastAPI backend
│   └── runner/              ← ARQ worker (per-step MCP dispatch)
│
├── packages/
│   ├── agent/               ← LiteLLM + LangGraph agent (stub — targets M3)
│   ├── db/                  ← SQLAlchemy 2 async + Alembic + seed
│   ├── mcp/                 ← MCP client + registry + pool + bundled providers
│   ├── shared/              ← cross-package Pydantic schemas
│   └── core/                ← capability resolver, autonomy, AES-GCM crypto
│
├── infra/
│   ├── docker/              ← Dockerfile per service
│   └── helm/suitest/        ← Helm chart
│
└── docs/                    ← see Documentation index below
```

---

## Documentation

**Start at [docs/ROADMAP.md](./docs/ROADMAP.md)** — it is the single entry point for picking up any feature. Open the spec docs below only when the roadmap item you're working on needs them.

| Doc | Topic |
|-----|-------|
| [ROADMAP.md](./docs/ROADMAP.md) | Milestones M0 → M15 + build status (start here) |
| [PRODUCT.md](./docs/PRODUCT.md) | Vision, personas, user journeys |
| [ARCHITECTURE.md](./docs/ARCHITECTURE.md) | Stack, services, topology |
| [DATA_MODEL.md](./docs/DATA_MODEL.md) | SQLAlchemy schema + entity diagram |
| [API.md](./docs/API.md) | REST + WebSocket contract |
| [UI_SPEC.md](./docs/UI_SPEC.md) | Per-screen component spec |
| [CAPABILITY_TIERS.md](./docs/CAPABILITY_TIERS.md) | ZERO/LOCAL/CLOUD gating |
| [MCP_PLUGINS.md](./docs/MCP_PLUGINS.md) | MCP registry + routing + sandbox security |
| [GENERATORS.md](./docs/GENERATORS.md) | Generator design (deterministic + LLM) |
| [AUTONOMY.md](./docs/AUTONOMY.md) | Per-workspace autonomy dial |
| [AI_AGENT.md](./docs/AI_AGENT.md) | Prompts + LangGraph + tool registry (spec, M3) |
| [DEPLOYMENT.md](./docs/DEPLOYMENT.md) | Compose / Helm / air-gapped |
| [Design memo](./docs/superpowers/specs/2026-05-26-suitest-oss-pivot-design.md) | OSS pivot decisions (source of truth) |

---

## How it compares

| Capability | TestRail | Playwright | TestSprite | **Suitest ZERO** | **Suitest CLOUD** |
|------------|:--:|:--:|:--:|:--:|:--:|
| First-class manual TCM | ✓ | ✗ | partial | ✓ | ✓ |
| Deterministic runner | ✗ | ✓ | ✓ | ✓ | ✓ |
| Universal MCP plugin layer | ✗ | ✗ | partial | ✓ | ✓ |
| AI generation / diagnosis | ✗ | ✗ | ✓ | ✗ | ✓ *(roadmap)* |
| Self-host | ✓ | ✓ | ✗ | ✓ | ✓ |
| BYO LLM (100+ providers) | n/a | n/a | ✗ locked | n/a | ✓ |
| Air-gapped | ✓ | ✓ | ✗ | ✓ | ✓ (Ollama) |
| Open source | ✗ | runner only | ✗ | ✓ | ✓ |

---

## Contributing

1. **Read [CLAUDE.md](./CLAUDE.md)** — binding conventions for this repo (also applies to AI coding agents).
2. **Pick the next unchecked item in [docs/ROADMAP.md](./docs/ROADMAP.md)** — one PR = one acceptance criterion. The roadmap tells you which spec doc to open.
3. **Branch:** `feat/<scope>-<short-desc>`. **Commits:** conventional commits (`feat(api): ...`).
4. **Before pushing:** `make ci` must pass (ruff + mypy strict, tsc strict + ESLint, pytest async + vitest).

`CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `SECURITY.md` land in M4 launch prep.

---

## License

**Apache License 2.0** — permissive, commercial-friendly. See [LICENSE](./LICENSE).

## Acknowledgments

Built on [Model Context Protocol](https://modelcontextprotocol.io) (Anthropic), [LiteLLM](https://github.com/BerriAI/litellm) (BerriAI), [LangGraph](https://langchain-ai.github.io/langgraph/) (LangChain), [`@ai-sdk/react`](https://sdk.vercel.ai/docs) + assistant-ui (Vercel), shadcn/ui, TanStack, and the FastAPI / SQLAlchemy / Pydantic ecosystems. 🎉
