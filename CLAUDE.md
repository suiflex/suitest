# CLAUDE.md — Suitest coding rules

> Binding context for every AI coding agent (Claude Code, Cursor, Cline, etc.) working in this repo. Read this **before** writing code.
>
> After the OSS pivot (2026-05-26), Suitest = **Python/FastAPI backend** + **Vite/React frontend** + **MCP-native plugin layer** + **capability tiering**.

---

## 1. What is Suitest

**MCP-native testing platform. Manual TCM, deterministic runs, autonomous AI when configured. Your stack, your LLM, your data.**

A self-hostable OSS platform that combines:

- **Manual TCM** — traditional test case editor (steps, expected, assertions, traceability)
- **Deterministic runner** — step execution via pluggable MCP servers (Playwright, API HTTP, Postgres, GraphQL, gRPC, Mongo, Kubernetes, custom)
- **AI generation (optional)** — when the user brings their own LLM key, agents generate from PRD / OpenAPI / URL / MCP discovery
- **AI diagnosis (optional)** — auto-categorize defects (FLAKE / REGRESSION / ENVIRONMENT / TEST_BUG) when an LLM is available
- **Capability-tiered** — features grow automatically from ZERO → LOCAL → CLOUD based on user configuration

Positioning: a replacement for TestRail + Playwright (ZERO tier) that also goes beyond TestSprite (CLOUD/LOCAL tier) without vendor lock-in.

Visual reference: [`docs/UI_SPEC.md`](./docs/UI_SPEC.md).

---

## 2. Working rules

### 2.1 Always do this first

**`docs/ROADMAP.md` is the single entry point.** To continue any feature, start there — pick the next acceptance criterion that is not yet `[x]` in the active milestone. The ROADMAP determines order and scope; do not work from memory or from another doc first.

Other spec docs are **conditional references**, opened ONLY when the ROADMAP item you are working on needs their detail:

| Open this doc | Only when the ROADMAP item… |
|--------------|---------------------------|
| `docs/PRODUCT.md` | needs feature behavior/persona context |
| `docs/UI_SPEC.md` | touches the frontend (components are already specified) |
| `docs/API.md` | adds/changes an endpoint |
| `docs/DATA_MODEL.md` | touches the schema — do not invent columns without a spec update + Alembic migration |
| `docs/CAPABILITY_TIERS.md` | is LLM-dependent — you must know the tier gating |
| `docs/MCP_PLUGINS.md` | touches the runner / MCP routing |
| `docs/AUTONOMY.md` | is an agentic action with side effects |

Every doc has a build-status banner at the top (built vs spec M2–M4) — read it before trusting the contents. If the ROADMAP and a spec conflict, **the ROADMAP wins**; update the spec in the same PR.

### 2.2 Don't

- Don't add new dependencies without updating `docs/ARCHITECTURE.md`
- Don't create persistent "demo data" — always use a Python seed script
- Don't hardcode credentials, API keys, or production URLs — use env vars
- Don't write barrel files (`__init__.py` re-exporting everything / `index.ts` re-exports) — import directly
- Don't use `Any` in Python (mypy strict) — use specific types, `TypedDict`, or `Protocol`
- Don't use `as any` in TypeScript — use narrowing / `unknown` + a Zod validator
- Don't call LLM SDKs directly from API routes — always go through `packages/agent` via LiteLLM
- Don't call MCP servers directly from API routes — always go through `packages/mcp/client`
- Don't skip **capability gating** for AI features — an LLM feature without `require_tier(...)` is a BUG
- Don't store any secret in plaintext — always AES-GCM via `packages/core/crypto`
- Don't skip the audit log for mutations — every write operation logs via the `audit_log` table

### 2.3 Must

- **Python 3.12** typed (mypy strict, `disallow_untyped_defs = true`)
- **Pydantic v2** schemas for all API input/output + DTOs
- **SQLAlchemy 2 async** + **Alembic** for all DB access (no raw SQL except performance-critical, with a `# perf: raw SQL` comment)
- **FastAPI** + dependency injection (no globals; every service injected via `Depends`)
- **Ruff** + **Black** + isort configured (one tool: ruff format)
- **pytest async** for testing (`pytest-asyncio` strict mode)
- **FE TypeScript strict** mode; Zod schemas validating API I/O on the client
- All **AI calls** go through `packages/agent` (LiteLLM router)
- All **MCP calls** go through `packages/mcp/client` (registry + pool)
- All **DB access** goes through the repository pattern (`packages/db/repositories/*.py`)
- **AES-GCM** for stored secrets via `packages/core/crypto`
- **Audit log** every mutation (`packages/db/audit.py`)
- Every new endpoint must declare its tier requirement via `Depends(require_tier(...))`
- Every LLM-dependent UI feature must be wrapped in `<Gated feature="...">`

---

## 3. Code conventions

### 3.1 Naming

- Python files: `snake_case.py`
- TS module files: `kebab-case.ts`
- React components: `PascalCase.tsx`
- DB tables: `snake_case`, plural (`test_cases`, `test_runs`, `mcp_providers`)
- API routes: `kebab-case` plural (`/api/v1/test-cases`, `/api/v1/mcp/providers`)
- Env vars: `SCREAMING_SNAKE_CASE`, prefix `SUITEST_*` (e.g. `SUITEST_DATABASE_URL`, `SUITEST_REDIS_URL`). The LLM is **not** configured via env — it is configured per-workspace from the web UI.
- Python classes: `PascalCase`
- Python functions/vars: `snake_case`
- Constants: `UPPER_SNAKE_CASE`

### 3.2 Folder conventions

**Backend (Python):**

```
apps/api/src/
├── main.py              ← FastAPI app factory
├── routers/             ← thin route handlers, call services
│   ├── test_cases.py
│   ├── runs.py
│   ├── mcp.py
│   ├── capabilities.py
│   └── ...
├── services/            ← business logic, transactional
│   ├── test_case_service.py
│   ├── run_service.py
│   └── ...
├── deps/                ← dependency injection providers
│   ├── auth.py          ← current_user, require_role
│   ├── tier.py          ← require_tier, require_autonomy
│   └── db.py            ← session provider
└── schemas/             ← Pydantic v2 request/response DTOs

apps/runner/src/
├── worker.py            ← ARQ entrypoint
├── jobs/                ← per-job handler (run_test_case, etc)
└── executors/           ← MCP step dispatcher

packages/agent/suitest_agent/
├── providers/           ← LiteLLM wrapper + mock
├── graphs/              ← LangGraph state machines per mode
├── prompts/             ← versioned prompt files
└── tools/               ← agent tool registry

packages/mcp/suitest_mcp/
├── client.py            ← MCP client abstraction
├── registry.py          ← provider lookup
├── pool.py              ← connection pooling
└── bundled/             ← bundled provider configs

packages/db/suitest_db/
├── models/              ← SQLAlchemy declarative
├── repositories/        ← repo pattern
├── migrations/          ← Alembic versions
└── audit.py             ← audit log helper

packages/shared/suitest_shared/
└── schemas/             ← cross-package Pydantic types

packages/core/suitest_core/
├── capabilities.py      ← tier resolver
├── autonomy.py          ← autonomy resolver
└── crypto.py            ← AES-GCM helper
```

**Frontend (Vite + React 19):**

```
apps/web/src/
├── routes/              ← TanStack Router file-based routes
│   ├── __root.tsx
│   ├── dashboard.tsx
│   ├── cases/index.tsx
│   ├── cases/$caseId.tsx
│   ├── runs/$runId.tsx
│   └── ...
├── components/
│   ├── ui/              ← shadcn primitives
│   ├── shell/           ← Sidebar, Topbar, AiPanel
│   ├── gating/          ← <Gated /> wrapper
│   ├── dashboard/
│   ├── cases/
│   ├── runs/
│   ├── mcp/             ← MCP provider browser
│   └── shared/
├── lib/
│   ├── api-client.ts    ← typed fetch (generated from OpenAPI)
│   ├── ws-client.ts     ← native WebSocket wrapper
│   └── utils.ts         ← cn(), formatters
├── stores/              ← Zustand (capabilities, ui-state, auth)
│   ├── use-capabilities.ts
│   └── use-autonomy.ts
└── styles/
    └── globals.css      ← Tailwind 4 + tokens
```

### 3.3 Design tokens (Tailwind)

Tokens are defined in `apps/web/tailwind.config.ts`. **Do not invent new colors.**

| Token | Value | Used for |
|-------|-------|-------------|
| `bg-base` | `#0a0a0a` | Body background |
| `bg-elev-1` | `#111` | Card surface |
| `bg-elev-2` | `#161616` | Hover / nested |
| `border` | `#262626` | Default border |
| `fg-1` | `#fafafa` | Primary text |
| `fg-3` | `#a3a3a3` | Secondary text |
| `fg-4` | `#737373` | Tertiary / muted |
| `accent` | `#4ade80` | Primary action, pass status |
| `red` | `#f87171` | Failures, critical |
| `amber` | `#fbbf24` | Warnings, flaky |
| `violet` | `#a78bfa` | AI-generated, agent-related |

Font: **Geist Sans** for UI, **Geist Mono** for code/IDs/numbers.

### 3.4 Copy / language

- Product UI: **English** by default. Additional locales live in the i18next dictionaries (`en`, `id`) — never hardcode non-English strings in components.
- Error messages: English, user-friendly
- Documentation and code comments: **English only**
- Agent chat: mirror the user's language in conversational replies; keep code, IDs, and technical terms in English

---

## 4. Capability tier rules

Suitest runs in 3 tiers (see [CAPABILITY_TIERS.md](./docs/CAPABILITY_TIERS.md)):

- **ZERO** — no LLM. Full TCM + deterministic runs + rule-based defects.
- **LOCAL** — local LLM (Ollama, llamacpp, vLLM, LM Studio). Full AI features.
- **CLOUD** — cloud LLM (anthropic, openai, gemini, groq, openrouter, ...). Full AI features.

> **The tier is resolved from the per-workspace LLM configuration (web UI: Settings → LLM provider), NOT from env.** The base deployment is always ZERO; the provider stored by the workspace (AES-encrypted) is what raises the tier (`build_workspace_overlay` / `CapabilityService.resolve`). There are no `SUITEST_LLM_*` / `SUITEST_EMBEDDINGS_BACKEND` env vars anymore. `resolve_tier()` / `resolve_embeddings()` in `packages/core/capabilities.py` are now ZERO-always (they only serve as the base + the `compute_features`/`compute_autonomy` primitives for the overlay).

### MANDATORY rules

- Every new endpoint declares its tier requirement via DI:
  ```python
  @router.post("/agent/generate")
  async def generate(..., _: None = Depends(require_tier(Tier.CLOUD | Tier.LOCAL))):
      ...
  ```
- Every LLM-dependent UI feature is wrapped in `<Gated>`:
  ```tsx
  <Gated feature="ai_generation" fallback={<UpgradeHint />}>
    <GenerateModal />
  </Gated>
  ```
- **Never assume an LLM is available** — the default code path must be ZERO-compatible. AI = enrichment on top of the deterministic core.
- LLM calls need a tier gate: `require_tier(Tier.CLOUD | Tier.LOCAL)`
- Agentic steps (with non-reversible side effects) need an autonomy gate: `require_autonomy(AutonomyLevel.ASSIST_OR_HIGHER)`
- **Test ZERO mode first**, then CLOUD, then LOCAL. The eval harness must be green at ZERO before LLM enrichment is merged.

---

## 5. MCP rules

MCP is the primary plugin layer. See [MCP_PLUGINS.md](./docs/MCP_PLUGINS.md).

### MANDATORY rules

- Never invoke an MCP server directly from an API route — always go through `packages/mcp/client`
- Every `Step` declares `mcp_provider` (TEXT) + `target_kind` (ENUM); if empty, default routing comes from the `target_kind` mapping
- When adding a bundled MCP, update:
  1. `packages/mcp/suitest_mcp/bundled/` config
  2. `packages/mcp/suitest_mcp/registry.py` default routing
  3. `docs/MCP_PLUGINS.md` (list + caveats)
  4. `docs/DEPLOYMENT.md` (Docker image bundling)
- User-provided MCP commands are **untrusted** — sandbox per [MCP_PLUGINS.md § security](./docs/MCP_PLUGINS.md):
  - Run in a container with restricted capabilities
  - No host filesystem access unless explicitly mounted
  - Egress whitelist via NetworkPolicy
  - Timeout enforcement (default 30s per tool call)
- Step output from MCP must be normalized via `packages/mcp/normalizer.py` before storing/streaming

---

## 6. Git workflow

- Branch per feature: `feat/<scope>-<short-desc>` (e.g. `feat/agent-prd-parser`)
- Commit messages: **conventional commits** — `feat(agent): add PRD parser` / `fix(api): handle 429 from anthropic`
- PR titles follow the same commit message style
- Every PR must: pass lint, mypy, typecheck, pytest, vitest, and mention the milestone (`Closes #M2-3`)
- Squash merge to `main` (one acceptance criterion = one commit on main)
- Before merging, wait for CI green + 1 review

---

## 7. When the AI agent is unsure

If you are unsure about something not covered in the docs:

1. **Check `docs/UI_SPEC.md`** first for visual / behavior hints
2. **Check `CAPABILITY_TIERS.md`** before implementing an LLM-dependent feature — make sure the tier gating is clear
3. If it is still ambiguous → **write the question in the PR description** before continuing
4. **Never guess field names, endpoints, or prompt keys** — ask for clarification

---

## 8. Vibe coding heuristics

- **ZERO tier first.** Every feature must work or gracefully degrade at ZERO before LLM enrichment is added. If your feature only works on CLOUD, redesign it.
- **Backend first, FE second.** Pydantic schema + Alembic migration + service test → then wire the UI.
- **Mock the LLM last.** For agent features, build against `packages/agent/providers/mock.py` deterministically first, real providers later.
- **Look at UI_SPEC, adapt for tier.** The spec describes the CLOUD-tier view. ZERO tier hides the AI parts; show an upgrade hint.
- **Small PRs win.** One PR = one acceptance criterion on the roadmap.
- **Dogfood always.** Once M3 is done, run Suitest's smoke suite using Suitest. Suitest tests Suitest.
- **The capability gate is non-negotiable.** An LLM feature without a gate = PR auto-blocked.

---

## 9. Glossary

| Term | Meaning |
|------|------|
| **TCM** | Test Case Management |
| **MCP** | Model Context Protocol — Anthropic-led standard for the agent tool layer |
| **Run** | One execution of one or more test cases |
| **Suite** | Logical grouping of test cases |
| **Gating** | A run that blocks deploys if it fails |
| **Flaky** | A test that alternates between pass and fail with no code change |
| **Traceability** | Link requirement ↔ test case ↔ defect |
| **Defect** | Bug record created from a test failure |
| **Artifact** | Output of a run (screenshot, HAR, log, video) |
| **Tier** | Capability level: `ZERO` / `LOCAL` / `CLOUD` — base is always ZERO, raised per-workspace by the LLM configuration in the web UI |
| **Autonomy** | Per-workspace dial: `manual` / `assist` / `semi_auto` / `auto` |
| **target_kind** | Enum: `BE_REST` / `BE_GRAPHQL` / `BE_GRPC` / `FE_WEB` / `FE_MOBILE` / `DATA` / `INFRA` / `CUSTOM` |
| **mcp_provider** | Foreign key into the MCP server registry (e.g. `playwright-mcp`, `api-http-mcp`) |
| **Generator** | Mechanism for creating test cases. Deterministic (OpenAPI, Recorder, Crawler) or LLM-driven (PRD, semantic URL, MCP discovery) |
| **Capability resolver** | `packages/core/capabilities.py` — supplies the ZERO base + primitives (tier → features/autonomy); the effective tier is raised by the service layer from the workspace LLMConfig |
| **Mixed-MCP test** | A single test case whose steps use different `mcp_provider`s (e.g. seed pg → call api → drive browser) |
| **ZERO mode** | Tier without an LLM. AI features hidden / disabled. Manual TCM + deterministic runs only. |
| **BYO LLM** | "Bring Your Own LLM" — the user provides their own API key (cloud) or runs one locally (Ollama) |
| **LiteLLM** | Router for 100+ providers via one client interface |
| **LangGraph** | State machine library for agent orchestration |
| **assistant-ui** | React component library for the AI chat panel |
