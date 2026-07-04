# CLAUDE.md — Suitest coding rules

> Binding context untuk semua AI coding agent (Claude Code, Cursor, Cline, dll) yang bekerja di repo ini. Baca **sebelum** menulis kode.
>
> Setelah pivot OSS (2026-05-26), Suitest = **Python/FastAPI backend** + **Vite/React frontend** + **MCP-native plugin layer** + **capability tiering**.

---

## 1. Apa itu Suitest

**MCP-native testing platform. Manual TCM, deterministic runs, autonomous AI when configured. Your stack, your LLM, your data.**

Platform OSS self-hostable yang menggabungkan:

- **Manual TCM** — editor test case tradisional (steps, expected, assertions, traceability)
- **Deterministic runner** — eksekusi step via MCP server pluggable (Playwright, API HTTP, Postgres, GraphQL, gRPC, Mongo, Kubernetes, custom)
- **AI generation (opsional)** — saat user bawa LLM key sendiri, agen generate dari PRD / OpenAPI / URL / MCP discovery
- **AI diagnosis (opsional)** — auto-categorize defect (FLAKE / REGRESSION / ENVIRONMENT / TEST_BUG) saat LLM tersedia
- **Capability-tiered** — fitur berkembang otomatis dari ZERO → LOCAL → CLOUD sesuai konfigurasi user

Posisi: replacement untuk TestRail + Playwright (ZERO tier) yang juga melampaui TestSprite (CLOUD/LOCAL tier) tanpa vendor lock-in.

Visual reference: [`docs/UI_SPEC.md`](./docs/UI_SPEC.md).

---

## 2. Aturan kerja

### 2.1 Selalu lakukan dulu

**`docs/ROADMAP.md` adalah satu-satunya pintu masuk.** Untuk melanjutkan fitur apapun, mulai di sana — pilih acceptance criterion berikutnya yang belum `[x]` di milestone aktif. ROADMAP yang nentuin urutan dan ruang lingkup; jangan kerja dari ingatan atau doc lain duluan.

Spec doc lain = **referensi kondisional**, dibuka HANYA saat item ROADMAP yang lagi dikerjakan butuh detailnya:

| Buka doc ini | Hanya kalau item ROADMAP… |
|--------------|---------------------------|
| `docs/PRODUCT.md` | butuh konteks behavior/persona fitur |
| `docs/UI_SPEC.md` | menyentuh frontend (komponen sudah dispesifikasi) |
| `docs/API.md` | menambah/mengubah endpoint |
| `docs/DATA_MODEL.md` | menyentuh schema — jangan invent kolom tanpa update spec + Alembic migration |
| `docs/CAPABILITY_TIERS.md` | fitur LLM-dependent — wajib tahu tier gating |
| `docs/MCP_PLUGINS.md` | menyentuh runner / MCP routing |
| `docs/AUTONOMY.md` | agentic action yang punya side effect |

Tiap doc punya banner build-status di atas (built vs spec M2–M4) — baca itu sebelum percaya isinya. Kalau ROADMAP dan spec bentrok, **ROADMAP menang**; update spec di PR yang sama.

### 2.2 Jangan

- Jangan tambah dependency baru tanpa update `docs/ARCHITECTURE.md`
- Jangan bikin "demo data" yang persistent — selalu pakai Python seed script
- Jangan hardcode credentials, API keys, atau URL produksi — pakai env vars
- Jangan write barrel files (`__init__.py` yang re-export semua / `index.ts` re-export) — import langsung
- Jangan pakai `Any` di Python (mypy strict) — pakai tipe spesifik, `TypedDict`, atau `Protocol`
- Jangan pakai `as any` di TypeScript — pakai narrowing / `unknown` + Zod validator
- Jangan call LLM SDK langsung dari API route — wajib lewat `packages/agent` via LiteLLM
- Jangan call MCP server langsung dari API route — wajib lewat `packages/mcp/client`
- Jangan skip **capability gating** untuk AI features — fitur LLM tanpa `require_tier(...)` adalah BUG
- Jangan store secret apapun plaintext — wajib AES-GCM lewat `packages/core/crypto`
- Jangan skip audit log untuk mutation — semua write operation log via `audit_log` table

### 2.3 Wajib

- **Python 3.12** typed (mypy strict, `disallow_untyped_defs = true`)
- **Pydantic v2** schemas untuk semua API input/output + DTO
- **SQLAlchemy 2 async** + **Alembic** untuk semua DB access (no raw SQL kecuali performance-critical, dan kasih komentar `# perf: raw SQL`)
- **FastAPI** + dependency injection (no globals; tiap service inject via `Depends`)
- **Ruff** + **Black** + isort configured (one tool: ruff format)
- **pytest async** untuk testing (`pytest-asyncio` strict mode)
- **FE TypeScript strict** mode; Zod schemas untuk API I/O divalidasi di client
- Semua **AI call** lewat `packages/agent` (LiteLLM router)
- Semua **MCP call** lewat `packages/mcp/client` (registry + pool)
- Semua **DB access** lewat repository pattern (`packages/db/repositories/*.py`)
- **AES-GCM** untuk stored secrets via `packages/core/crypto`
- **Audit log** every mutation (`packages/db/audit.py`)
- Setiap endpoint baru harus declare tier requirement via `Depends(require_tier(...))`
- Setiap UI feature LLM-dependent harus dibungkus `<Gated feature="...">`

---

## 3. Convention kode

### 3.1 Naming

- Files Python: `snake_case.py`
- Files TS modules: `kebab-case.ts`
- React components: `PascalCase.tsx`
- DB tables: `snake_case`, plural (`test_cases`, `test_runs`, `mcp_providers`)
- API routes: `kebab-case` plural (`/api/v1/test-cases`, `/api/v1/mcp/providers`)
- Env vars: `SCREAMING_SNAKE_CASE`, prefix `SUITEST_*` (e.g. `SUITEST_DATABASE_URL`, `SUITEST_REDIS_URL`). LLM **bukan** via env — dikonfigurasi per-workspace dari web UI.
- Python classes: `PascalCase`
- Python functions/vars: `snake_case`
- Constants: `UPPER_SNAKE_CASE`

### 3.2 Folder konvensi

**Backend (Python):**

```
apps/api/src/
├── main.py              ← FastAPI app factory
├── routers/             ← thin route handlers, panggil services
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
│   ├── api-client.ts    ← typed fetch (generated dari OpenAPI)
│   ├── ws-client.ts     ← native WebSocket wrapper
│   └── utils.ts         ← cn(), formatters
├── stores/              ← Zustand (capabilities, ui-state, auth)
│   ├── use-capabilities.ts
│   └── use-autonomy.ts
└── styles/
    └── globals.css      ← Tailwind 4 + tokens
```

### 3.3 Design tokens (Tailwind)

Token ditetapkan di `apps/web/tailwind.config.ts`. **Jangan invent warna baru.**

| Token | Value | Pakai untuk |
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

Font: **Geist Sans** untuk UI, **Geist Mono** untuk code/IDs/numbers.

### 3.4 Copy / language

- Product UI: **English** (Dashboard, Test Cases, Run now)
- Marketing / empty states / agent dialog: **Bahasa Indonesia** boleh dicampur ("Selamat siang, Maya")
- Error messages: English, user-friendly
- Doc internal: campuran Indonesian/English OK

---

## 4. Capability tier rules

Suitest jalan di 3 tier (lihat [CAPABILITY_TIERS.md](./docs/CAPABILITY_TIERS.md)):

- **ZERO** — no LLM. Full TCM + deterministic run + rule-based defect.
- **LOCAL** — local LLM (Ollama, llamacpp, vLLM, LM Studio). Full AI features.
- **CLOUD** — cloud LLM (anthropic, openai, gemini, groq, openrouter, ...). Full AI features.

> **Tier di-resolve dari konfigurasi LLM per-workspace (web UI: Settings → LLM provider), BUKAN dari env.** Base deployment selalu ZERO; provider yang disimpan workspace (AES-encrypted) yang menaikkan tier (`build_workspace_overlay` / `CapabilityService.resolve`). Tidak ada lagi env `SUITEST_LLM_*` / `SUITEST_EMBEDDINGS_BACKEND`. `resolve_tier()` / `resolve_embeddings()` di `packages/core/capabilities.py` sekarang ZERO-always (cuma jadi base + primitive `compute_features`/`compute_autonomy` untuk overlay).

### Rules WAJIB

- Setiap endpoint baru declare tier requirement via DI:
  ```python
  @router.post("/agent/generate")
  async def generate(..., _: None = Depends(require_tier(Tier.CLOUD | Tier.LOCAL))):
      ...
  ```
- Setiap UI feature LLM-dependent bungkus dengan `<Gated>`:
  ```tsx
  <Gated feature="ai_generation" fallback={<UpgradeHint />}>
    <GenerateModal />
  </Gated>
  ```
- **Jangan asumsi LLM tersedia** — default code path harus ZERO-compatible. AI = enrichment di atas deterministic core.
- LLM call butuh tier gate: `require_tier(Tier.CLOUD | Tier.LOCAL)`
- Agentic step (yang punya side effect non-reversible) butuh autonomy gate: `require_autonomy(AutonomyLevel.ASSIST_OR_HIGHER)`
- **Test ZERO mode dulu**, baru CLOUD, baru LOCAL. Eval harness wajib green di ZERO sebelum LLM enrichment di-merge.

---

## 5. MCP rules

MCP = primary plugin layer. Lihat [MCP_PLUGINS.md](./docs/MCP_PLUGINS.md).

### Rules WAJIB

- Jangan invoke MCP server langsung dari API route — wajib lewat `packages/mcp/client`
- Setiap `Step` declare `mcp_provider` (TEXT) + `target_kind` (ENUM); kalau kosong, default routing dari `target_kind` mapping
- Saat nambah bundled MCP, update:
  1. `packages/mcp/suitest_mcp/bundled/` config
  2. `packages/mcp/suitest_mcp/registry.py` default routing
  3. `docs/MCP_PLUGINS.md` (list + caveat)
  4. `docs/DEPLOYMENT.md` (Docker image bundling)
- User-provided MCP commands = **untrusted** — sandbox per [MCP_PLUGINS.md § security](./docs/MCP_PLUGINS.md):
  - Run in container with restricted capabilities
  - No host filesystem access kecuali explicitly mounted
  - Egress whitelist via NetworkPolicy
  - Timeout enforcement (default 30s per tool call)
- Step output dari MCP harus dinormalisasi via `packages/mcp/normalizer.py` sebelum simpan/stream

---

## 6. Git workflow

- Branch per fitur: `feat/<scope>-<short-desc>` (misal `feat/agent-prd-parser`)
- Commit message: **conventional commits** — `feat(agent): add PRD parser` / `fix(api): handle 429 from anthropic`
- PR title sama dengan commit message style
- Setiap PR harus: lint pass, mypy pass, typecheck pass, pytest pass, vitest pass, mention milestone (`Closes #M2-3`)
- Squash merge ke `main` (one acceptance criterion = one commit di main)
- Sebelum merge, tunggu CI green + 1 review

---

## 7. Saat AI agent ragu

Kalau tidak yakin tentang sesuatu yang tidak ada di docs:

1. **Cek `docs/UI_SPEC.md`** dulu untuk hint visual / behavior
2. **Cek `CAPABILITY_TIERS.md`** sebelum implement fitur LLM-dependent — pastikan tier gating jelas
3. Kalau masih ambigu → **tulis pertanyaan di PR description** sebelum lanjut
4. **Jangan tebak nama field, endpoint, atau prompt key** — minta klarifikasi

---

## 8. Vibe coding heuristics

- **ZERO tier first.** Setiap fitur harus jalan atau gracefully degrade di ZERO sebelum LLM enrichment ditambahkan. Kalau fitur kamu cuma jalan di CLOUD, design ulang.
- **Backend first, FE second.** Pydantic schema + Alembic migration + service test → baru wire UI.
- **Mock the LLM last.** Untuk agent features, build via `packages/agent/providers/mock.py` deterministic dulu, real provider belakangan.
- **Look at UI_SPEC, adapt for tier.** Spec menggambarkan CLOUD-tier view. ZERO-tier hide bagian AI; tunjukkan upgrade hint.
- **Small PRs win.** Satu PR = satu acceptance criterion di roadmap.
- **Dogfood always.** Begitu M3 selesai, jalankan smoke suite Suitest pakai Suitest. Suitest test Suitest.
- **Capability gate is non-negotiable.** Fitur LLM tanpa gate = PR auto-blocked.

---

## 9. Glossary

| Term | Arti |
|------|------|
| **TCM** | Test Case Management |
| **MCP** | Model Context Protocol — Anthropic-led standard untuk agent tool layer |
| **Run** | One execution of one or more test cases |
| **Suite** | Logical grouping of test cases |
| **Gating** | A run that blocks deploy jika gagal |
| **Flaky** | Test yang kadang pass kadang fail tanpa perubahan kode |
| **Traceability** | Link requirement ↔ test case ↔ defect |
| **Defect** | Bug record dari test failure |
| **Artifact** | Output dari run (screenshot, HAR, log, video) |
| **Tier** | Capability level: `ZERO` / `LOCAL` / `CLOUD` — base selalu ZERO, dinaikkan per-workspace dari konfigurasi LLM web UI |
| **Autonomy** | Per-workspace dial: `manual` / `assist` / `semi_auto` / `auto` |
| **target_kind** | Enum: `BE_REST` / `BE_GRAPHQL` / `BE_GRPC` / `FE_WEB` / `FE_MOBILE` / `DATA` / `INFRA` / `CUSTOM` |
| **mcp_provider** | Foreign key ke MCP server registry (e.g. `playwright-mcp`, `api-http-mcp`) |
| **Generator** | Mekanisme bikin test case. Deterministic (OpenAPI, Recorder, Crawler) atau LLM-driven (PRD, semantic URL, MCP discovery) |
| **Capability resolver** | `packages/core/capabilities.py` — supply ZERO base + primitive (tier → features/autonomy); tier efektif dinaikkan service layer dari LLMConfig workspace |
| **Mixed-MCP test** | Single test case dengan step menggunakan `mcp_provider` berbeda-beda (e.g. seed pg → call api → drive browser) |
| **ZERO mode** | Tier tanpa LLM. Fitur AI hidden / disabled. Manual TCM + deterministic run only. |
| **BYO LLM** | "Bring Your Own LLM" — user pasang API key sendiri (cloud) atau jalankan lokal (Ollama) |
| **LiteLLM** | Router 100+ provider via 1 client interface |
| **LangGraph** | State machine library untuk agent orchestration |
| **assistant-ui** | React component lib untuk AI chat panel |
