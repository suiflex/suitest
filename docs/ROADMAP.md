# docs/ROADMAP.md

> Milestones untuk Suitest OSS. **ZERO-tier first**: setiap fitur harus jalan di ZERO mode sebelum AI/LLM enrichment ditambahkan. Setiap PR reference satu acceptance criterion (`Closes #M2-3`). Kerjakan berurutan dalam satu milestone.

Source-of-truth memo: [`superpowers/specs/2026-05-26-suitest-oss-pivot-design.md`](./superpowers/specs/2026-05-26-suitest-oss-pivot-design.md).

Cross-reference: [PRODUCT.md](./PRODUCT.md), [ARCHITECTURE.md](./ARCHITECTURE.md), [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md), [MCP_PLUGINS.md](./MCP_PLUGINS.md), [AUTONOMY.md](./AUTONOMY.md), [GENERATORS.md](./GENERATORS.md), [DEPLOYMENT.md](./DEPLOYMENT.md).

---

## Phases

- **v1.0** = M0 → M4. Public OSS launch readiness. ZERO tier complete, CLOUD + LOCAL tier online, SDK/CLI shipped.
- **v1.x** = M5 → M9. Tier B polish features post-launch.
- **v2.x** = M10 → M15. Tier C agentic + advanced features.

---

# v1.0

---

## M0 — Skeleton OSS (1–2 minggu)

**Goal:** Repo bootable. Belum ada fitur, baru fondasi monorepo + boot sequence.

### Acceptance criteria

- [x] **M0-1** Monorepo: `uv` workspace untuk Python (`apps/api`, `apps/runner`, `packages/agent`, `packages/db`, `packages/mcp`, `packages/shared`, `packages/core`); `pnpm` workspace untuk FE (`apps/web`) (shipped at `e37c486` / tag `v0.1.0-m0`)
- [x] **M0-2** Lint/format/typecheck: ruff + mypy strict (Python), tsc + eslint + prettier (TS); pre-commit hooks aktif (shipped at `ba03eb2` / tag `v0.1.0-m0`)
- [x] **M0-3** `apps/web` Vite 6 + React 19 boot ke "Suitest" page dengan shadcn/ui + Tailwind 4 + Geist font loaded (shipped at `6c9b47c` / tag `v0.1.0-m0`)
- [x] **M0-4** `apps/api` FastAPI boot; `GET /health` returns `{ status: "ok" }`; `GET /capabilities` returns `{ tier: "ZERO", autonomy: "manual", llm_provider: null }` (shipped at `4b1db50` + `f22931d` / tag `v0.1.0-m0`)
- [x] **M0-5** Docker Compose: postgres-16 + pgvector, redis, minio untuk lokal dev (shipped at `74d74be` / tag `v0.1.0-m0`)
- [x] **M0-6** SQLAlchemy 2 async + Alembic init migration applied (schema kosong dulu, populated di M1) (shipped at `95d5523` / tag `v0.1.0-m0`)
- [x] **M0-7** **Minimal seed only:** create root workspace `Nusantara Retail` with **1 user** (workspace owner) — no projects, no suites, no cases, no integrations. Full seed (suites/cases/runs/defects/requirements/integrations) is **deferred to M1a** — see [`M1a-9`](#m1) below. Rationale: full schema (projects, suites, cases, runs, defects, requirements, integrations) does not land until M1a; a 1-row workspace insert is sufficient at M0 to validate the engine/migration pipeline. See [plan-01 §11.7 + spec-gaps](./superpowers/plans/2026-05-26-plan-01-m0-skeleton.md). (shipped at `f8551a7` / tag `v0.1.0-m0`)
- [x] **M0-8** FastAPI-Users dengan email/password + Google OAuth; redirect ke `/dashboard` setelah login (shipped at `46f910b` + `41984ab` / tag `v0.1.0-m0`)
- [x] **M0-9** GitHub Actions CI: ruff + mypy + pytest + tsc + vitest + build Docker images per service (shipped at `e9f381d` / tag `v0.1.0-m0`)
- [x] **M0-10** `docker compose up` membawa naik seluruh stack (api + web + runner + pg + redis + minio) — single command bootable (shipped at `c67954f` / tag `v0.1.0-m0`)
- [x] **M0-11** Helm chart skeleton di `infra/helm/suitest/` lulus `helm lint` (shipped at `5464569` / tag `v0.1.0-m0`)

### Definition of done

`git clone` → `cp .env.example .env` → `docker compose up -d` → buka `localhost:3000` → login → empty dashboard tampil dengan badge **ZERO** di topbar. Tidak ada fitur, tidak ada LLM call.

---

## M1 — ZERO mode end-to-end (3 minggu)

**Goal:** ZERO tier fully usable. Manual TCM + deterministic run via MCP + rule-based defect filing. **NO LLM CODE YET.** Target: ZERO mode sudah jadi TestRail+Playwright replacement yang competent.

### Acceptance criteria

### M1a — read-only TCM REST

#### Seed (full)

- [x] **M1a-9** Full idempotent seed (`uv run python -m packages.db.seed`) builds workspace **Nusantara Retail** with **1 owner + 2 members, 1 project, 4 suites, 18 cases, 5 runs, 3 defects, 6 requirements, 9 integrations** (kinds as shipped: `GITHUB` active, `JIRA` active, `SLACK` disconnected, `LINEAR` disconnected, `JENKINS` disconnected, `MCP_BROWSER_USE` disconnected, `MCP_PLAYWRIGHT` active, `MCP_API` active, `MCP_POSTGRES` disconnected). Replays cleanly on a populated DB (`INSERT … ON CONFLICT DO NOTHING`). Inherits the deferred work from M0-7. Source: [`packages/db/src/suitest_db/seed.py`](../packages/db/src/suitest_db/seed.py). Spec: [DATA_MODEL.md §11](./DATA_MODEL.md#11-seed-data). (shipped at `05f171e` / tag `v0.2.0-m1a`)

### M1b — read-only shell + screens

#### Shell + read-only views (capability-gated)

- [x] **M1-1** Sidebar dengan nav items + active route highlight + workspace picker (shipped at `80236c3` / tag `v0.3.0-m1b`)
- [x] **M1-2** Topbar dengan breadcrumbs dinamis + tier badge (`ZERO`) + ⌘K search palette (shipped at `6a88bfe` / tag `v0.3.0-m1b`)
- [x] **M1-3** AI Panel komponen exists tapi **hidden via `<Gated feature="ai_panel">`** di ZERO (shipped at `ec003ed` / tag `v0.3.0-m1b`)
- [x] **M1-4** Dashboard: KPIs, pass-rate chart, coverage bars, recent runs, readiness gauge (semua dari API) (shipped at `fe478d2` / tag `v0.3.0-m1b`)
- [x] **M1-5** Test Cases list + tree + detail panel (read-only mode) (shipped at `591feea` / tag `v0.3.0-m1b`)
- [x] **M1-6** Test Runs list + detail panel + log viewer (shipped at `364ad6a` / tag `v0.3.0-m1b`)
- [x] **M1-7** Defects list dengan cards (shipped at `f0d4e7a` / tag `v0.3.0-m1b`)
- [x] **M1-8** Analytics dengan gauges + pass-rate trend + flaky list + heatmap (shipped at `d5ea096` / tag `v0.3.0-m1b`)
- [x] **M1-9** Traceability matrix 3-column (shipped at `c66d7b7` / tag `v0.3.0-m1b`)
- [x] **M1-10** Integrations grid (shipped at `1aacb72` / tag `v0.3.0-m1b`)
- [x] **M1-11** Docs & specs grid (shipped at `8746302` / tag `v0.3.0-m1b`)

### M1c — runner + MCP routing

#### Runner dengan MCP (deterministic only)

- [x] **M1-16** `packages/mcp` registry + client + connection pool
- [x] **M1-17** Bundled MCP providers (minimum 3 untuk v1.0 M1): `playwright-mcp`, `api-http-mcp`, `postgres-mcp`
- [x] **M1-18** ARQ worker (`apps/runner`) pull run jobs, dispatch per-step ke MCP yang benar berdasarkan `step.mcp_provider`
- [x] **M1-19** WebSocket log streaming + screenshot capture per step + MinIO artifact upload
- [x] **M1-20** Run cancel + rerun (scheduled cron runs deferred to M1d)

### M1d — manual TCM writes + integrations

#### Manual TCM

- [ ] **M1-12** Create/edit test case dengan steps (`action` + `code` + `mcp_provider` + `target_kind`)
- [ ] **M1-13a** Case soft-delete dengan undo toast
- [ ] **M1-13b** Suite cascade soft-delete dengan undo toast
- [ ] **M1-13c** Project + requirement soft-delete dengan undo toast
- [x] **M1-14** Drag-reorder steps via dnd-kit
- [ ] **M1-15a** Bulk endpoint backend (delete, move to suite, change priority)
- [x] **M1-15b** Bulk-ops sticky bar FE

#### Defect (no AI)

- [ ] **M1-21** Saat step fail → rule-based defect creation, category `MANUAL_TRIAGE` (no diagnosis yet)
- [ ] **M1-22a** Integration CRUD + secrets (Jira / Linear / GitHub via OAuth atau PAT)
- [ ] **M1-22b** Defect sync-external + webhook receiver (file issue saat defect lahir)
- [ ] **M1-23** Defect status flow (Open → In Progress → Resolved → Closed)

#### Traceability + Analytics + Integrations

- [ ] **M1-24** Requirement CRUD + linking ke case
- [ ] **M1-25** Traceability matrix fully functional (req ↔ case ↔ defect)
- [ ] **M1-26** Analytics: pass rate, coverage, flaky (rule-based: outcome variance > 20%), heatmap, readiness
- [ ] **M1-27a** Slack adapter (notifications)
- [ ] **M1-27b** GitHub webhook (receives PR event → trigger run)
- [ ] **M1-27c** GitLab webhook (receives MR event → trigger run)
- [ ] **M1-27d** Jira webhook sync-back

#### Quality

- [ ] **M1-28** E2E test (Playwright in CI) covering golden path: login → create case → run → see result
- [ ] **M1-29** Visual regression vs `Suitest.html` mockup ≥ 95% match per screen
- [ ] **M1-30** Loading + empty + error states untuk semua screens

### Definition of done

ZERO-tier deploy = TestRail+Playwright replacement yang competent. Maya bisa author cases, run via MCP, lihat defects, traceability. **Tidak ada AI, tidak ada LLM call ever dibuat.**

### M1e — local auth + invite-only onboarding

#### Self-host account management

- [ ] **M1e-1** First-install super-admin bootstrap from `SUITEST_SUPERADMIN_EMAIL` + `SUITEST_SUPERADMIN_PASSWORD`, idempotent when users already exist.
- [ ] **M1e-2** Password login is primary; Google OAuth remains optional secondary; public `/auth/register` disabled.
- [ ] **M1e-3** Stateful invitations: create/list/revoke/resend, token hash storage, ADMIN+ gate, raw link returned once.
- [ ] **M1e-4** `/accept-invite` public route creates user + workspace membership + session cookie.
- [ ] **M1e-5** Current user password change endpoint and Settings -> Account flow; `must_change_password` enforced after admin reset.
- [ ] **M1e-6** Super-admin password reset returns one-time temporary password and stores only password hash.
- [ ] **M1e-7** Interim forgot-password flow stores encrypted reset links for super-admin review until SMTP exists.
- [ ] **M1e-8** Docs/OpenAPI updated and ZERO-mode login/invite tests pass.

### Definition of done

Self-host install can be operated without OAuth: bootstrap super-admin logs in with password, invites users by copyable link, and users can accept invites and manage passwords. **No LLM/MCP behavior changes.**

---

## M2 — Generators + MCP plugin expansion (3 minggu)

**Goal:** Deterministic generators online + custom MCP registration end-to-end. Masih no LLM.

### Acceptance criteria

#### Deterministic generators (jalan di ZERO)

- [ ] **M2-1** OpenAPI generator (`POST /generators/openapi`) — parse spec → per-operation contract suite (happy + schema validate + required field + auth negative)
- [ ] **M2-2** Browser Recorder — start recording session → user demo → finalize → test case (pakai Playwright MCP recorder feature)
- [ ] **M2-3** Heuristic URL crawler — BFS depth-N, Faker form fill, klik tombol/link → skeleton smoke cases
- [ ] **M2-4** Target classifier (`POST /generators/classify`) deterministik — input URL/spec → `target_kind` + suggested MCP
- [ ] **M2-5** Generation modal UI dengan 3 strategi deterministik fully functional

#### MCP plugin universal

- [ ] **M2-6** MCP Provider registry CRUD UI + API (`GET/POST/DELETE /mcp/providers`)
- [ ] **M2-7** Custom MCP server registration end-to-end (user passes stdio/SSE/WS endpoint → tested → tersimpan)
- [ ] **M2-8** MCP tool browser (developer aid) — connect → list tools → invoke ad-hoc
- [ ] **M2-9** Routing override per workspace (`target_kind` → `mcp_provider` mapping editable)
- [ ] **M2-10** Bundled MCPs expanded (additive): `graphql-mcp`, `mongo-mcp`, `mysql-mcp`, `kubernetes-mcp`, `grpc-mcp`
- [ ] **M2-11** Mixed-MCP test case execution proven E2E — demo: seed pg → login api → checkout browser → verify api → verify db

#### Export

- [ ] **M2-12** Test code export (`GET /test-cases/:id/export?target=playwright|cypress|selenium`) — generate runnable script dari `step.code`

### Definition of done

ZERO tier bisa generate AND test melawan target apapun yang MCP-equipped. Custom MCP registration works. Mixed-MCP E2E demo green.

---

## M3 — LLM tier: CLOUD activation (4 minggu)

**Goal:** BYO LLM key. AI generation + diagnosis + conversation. Autonomy dial functional.

### Acceptance criteria

#### LLM foundation

- [ ] **M3-1** LiteLLM integration di `packages/agent` (100+ provider via 1 client)
- [ ] **M3-2** `LLMConfig` table + AES-GCM encryption untuk stored keys + Settings → LLM page (write-only key input + test connection)
- [ ] **M3-3** Tier resolver: `LLMConfig` change → `WorkspaceCapability` refresh → `GET /capabilities` mutated tier
- [ ] **M3-4** LangGraph state machines untuk 4 mode agent: `generation`, `execution`, `diagnosis`, `conversation`
- [ ] **M3-5** Versioned prompts + run reproducibility: persist `prompt_version_id`, `model_id`, `seed`, `temperature` per `AgentSession`

#### LLM-driven generators

- [ ] **M3-6** PRD natural-language generation — agent ekstrak user story → draft cases + edge variants
- [ ] **M3-7** URL semantic generation via browser-use AI agent (paham intent: "checkout flow")
- [ ] **M3-8** OpenAPI enrich — deterministic core + AI edge cases (boundary, fuzz, negative)
- [ ] **M3-9** MCP tool discovery generation — connect ke custom MCP, LLM eksplorasi tools, propose cases

#### Runtime + diagnosis

- [ ] **M3-10** Action→Code runtime translation: step yang cuma punya `action` di-translate ke MCP call saat execution
- [ ] **M3-11** AI diagnosis on failure (menggantikan `MANUAL_TRIAGE` → `REGRESSION` / `FLAKE` / `INFRA` / `SPEC_DRIFT` / `MANUAL_TRIAGE` + confidence) (canonical: DATA_MODEL.md §3.x DiagnosisKind enum)
- [ ] **M3-12** AI panel chat (conversation mode) pakai `assistant-ui` + `@ai-sdk/react`
- [ ] **M3-13** Streaming: SSE untuk token output + WebSocket untuk tool call events

#### Cost + autonomy

- [ ] **M3-14** Cost tracking per session + per workspace via LiteLLM cost calculation + budget guard (soft alert)
- [ ] **M3-15** Autonomy levels (`manual` / `assist` / `semi_auto` / `auto`) + Settings → Automation page
- [ ] **M3-16** Per-feature autonomy overrides (`generation`, `execution`, `diagnosis`, `defect_file`)

### Definition of done

CLOUD tier works dengan ≥ 5 provider tested: anthropic, openai, gemini, groq, openrouter. Autonomy `assist` functional (AI proposes → human approves). Cost transparency visible di UI.

---

## M4 — LOCAL tier polish + ship-ready (3 minggu)

**Goal:** Production-grade. Local LLM. SDK + CLI. Eval harness. Public OSS launch.

### Acceptance criteria

#### LOCAL tier

- [ ] **M4-1** LOCAL tier validated dengan: Ollama, llamacpp server, vLLM, LM Studio
- [ ] **M4-2** `fastembed` local embeddings (BAAI/bge-small, 384d) → semantic search berfungsi di ZERO+fastembed combo

#### Deploy

- [ ] **M4-3** Helm chart production-grade: HPA, readiness/liveness probes, NetworkPolicy, PodDisruptionBudget
- [ ] **M4-4** Air-gapped deploy validated — run k8s tanpa outbound network (semua image preloaded, Ollama in-cluster)

#### SDK + CLI

- [ ] **M4-5** `suitest-py` SDK published ke PyPI (generated dari OpenAPI)
- [ ] **M4-6** `@suitest/sdk` TS SDK published ke npm
- [ ] **M4-7** `suitest` CLI: `suitest run --suite smoke --branch main`, `suitest cases list`, `suitest mcp ls`

#### Eval + observability

- [ ] **M4-8** Eval harness backend (`POST /eval/runs`, `GET /eval/runs/:id`) + golden fixtures: 20 PRDs, 10 OpenAPI specs, 15 failed runs
- [ ] **M4-8a** **Eval fixture licensing audit.** Audit all eval fixtures (20 PRDs, 10 OpenAPI specs, 15 failed runs) for licensing compatibility. Required: CC0 / Apache-2 / MIT / public domain. No proprietary or scraped content. Document license per fixture in `eval/fixtures/LICENSES.md`. Reject incompatible fixtures and substitute with synthetic equivalents. Spec: [AI_AGENT.md §15 eval suite](./AI_AGENT.md#15-testing-the-agent).
- [ ] **M4-9** Cost dashboard per workspace, per provider, per generation kind
- [ ] **M4-10** Time-travel run replay UI (read-only step-through dengan screenshots + LLM messages)
- [ ] **M4-11** Observability: OpenTelemetry traces wired, Prometheus `/metrics`, optional Langfuse compose service

#### Polish

- [ ] **M4-12** i18n: English + Bahasa Indonesia
- [ ] **M4-13** a11y audit pass (axe DevTools no critical violations)
- [ ] **M4-14** Documentation site (Mintlify atau Astro Starlight) dengan getting-started + API reference + tutorial
- [ ] **M4-15** Example projects di `examples/`: `playwright-e2e`, `openapi-contract`, `mixed-mcp-e2e`, `air-gapped-deploy`
- [ ] **M4-16** Dogfood: Suitest tests Suitest in CI (smoke suite green di main pipeline)

#### Workspace portability + operational hardening

- [ ] **M4-29** **Workspace export.** `POST /workspaces/:id/export` returns signed URL to download `workspace-<id>-<timestamp>.tar.gz` containing: all entities as JSON (workspace meta + projects + suites + cases + steps + runs metadata + defects + requirements + integrations [secrets **REDACTED**]), artifacts manifest (list of MinIO keys + signed URLs valid 24h), prompts (versioned), LLM config (REDACTED), audit log up to N days. Background ARQ job assembles archive, uploads to MinIO with TTL 7d. Use case: compliance audit, migrate self-host, backup. Cross-ref: [API.md §3.1 workspaces](./API.md#31-auth--workspace), [DATA_MODEL.md §11 seed](./DATA_MODEL.md#11-seed-data).
- [ ] **M4-30** **Workspace import.** `POST /workspaces/import` with multipart upload of export archive. Validates schema version compatibility, dedupes by `public_id`, creates new workspace. Secrets MUST be re-entered manually (not part of import). Use case: restore from export, clone for staging.
- [ ] **M4-31** **External webhook retry queue.** All external API calls (Jira / Linear / GitHub / Slack / GitLab) go through `WebhookRetryQueue` (ARQ job with exponential backoff: 1s, 5s, 30s, 5m, 1h, 6h, 24h, max 7 attempts). DB table `webhook_dispatch_attempts(id, integration_id, payload_hash, attempt_n, status, error, created_at, next_retry_at)` — schema added in M4 migration. Dead letter: after 7 failures, mark integration `status=error` and surface in UI. Idempotency: callers must provide idempotency key; queue dedups. Use case: Jira/Slack 5xx common, prevents data loss. Cross-ref: [DATA_MODEL.md §3.8 integrations](./DATA_MODEL.md#38-integrations-kind-enum-expanded).
- [ ] **M4-32** **Audit log rotation + archival.** Schema already exists (`audit_logs` table from M1a). ARQ scheduled job (daily): rows older than `SUITEST_AUDIT_LOG_RETENTION_DAYS` (default `365`) moved to MinIO cold storage as compressed JSONL per workspace per month (`s3://suitest-archive/audit/<workspace_id>/<YYYY-MM>.jsonl.gz`). Hot DB table only keeps last 365 days. Optional restore endpoint `POST /audit/restore?from=<YYYY-MM>&workspace_id=<id>` re-imports archived month to query. Use case: compliance retention + DB bloat prevention. Cross-ref: [DATA_MODEL.md §3.11 audit log](./DATA_MODEL.md#311-audit-log), [DATA_MODEL.md §9 soft-delete & retention](./DATA_MODEL.md#9-soft-delete--retention).

#### Launch readiness

- [ ] **M4-17** OSS launch files: `LICENSE` (**Apache 2.0**), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `.github/ISSUE_TEMPLATE/*`, `.github/PULL_REQUEST_TEMPLATE.md`

### Definition of done

Tag `v1.0.0`. Announce di HN / Reddit / dev.to. Discord + community forum set up. First 10 community installations confirmed berhasil.

---

# v1.x — Tier B (post-launch)

## M5 — Time-travel & Eval UI (3 minggu)

- [ ] **M5-1** Full time-travel replay UI dengan diff viewer (state delta per step)
- [ ] **M5-2** Eval suite UI: define golden datasets, weekly CI run, score regression dashboard
- [ ] **M5-3** Versioned prompt fork per workspace (DB-backed override layer di atas file-based defaults)
- [ ] **M5-4** Prompt A/B testing harness

## M6 — Diff-aware test selection (3 minggu)

- [ ] **M6-1** Git diff parser → impact analysis via LLM → run only relevant cases for PR
- [ ] **M6-2** 10x faster CI untuk large suites benchmarked
- [ ] **M6-3** Requires CLOUD tier (LLM-driven); fallback ke full-run di ZERO

## M7 — Cost dashboard + budget guard full (2 minggu)

- [ ] **M7-1** Per-user spending limits enforced
- [ ] **M7-2** Auto-downgrade model rules (e.g., > $10/run → switch to cheaper model)
- [ ] **M7-3** Hard stop on budget exceeded (block new LLM calls)
- [ ] **M7-4** Spend alerts via Slack / email

## M8 — Custom agent definition (4 minggu)

- [ ] **M8-1** YAML / Python plugin: define agent role, prompt, tool whitelist, model preference
- [ ] **M8-2** Example: `SecurityAgent` untuk pentesting flow; `A11yAgent` untuk accessibility check
- [ ] **M8-3** Plugin SDK `suitest.plugins` (Python entrypoint discovery)

## M9 — Plugin SDK (3 minggu)

- [ ] **M9-1** Custom MCP via Python entrypoint
- [ ] **M9-2** Custom reporter plugin (e.g., XRay, qTest)
- [ ] **M9-3** Custom integration adapter (e.g., Asana, ClickUp)
- [ ] **M9-4** Marketplace concept page (list community plugins)

---

# v2.x — Tier C

## M10 — Self-healing tests (5 minggu)

- [ ] **M10-1** Selector changed detection
- [ ] **M10-2** AI repair → propose updated step
- [ ] **M10-3** Save updated step (gated by autonomy)
- [ ] **M10-4** Requires `auto` autonomy level untuk full self-heal

## M11 — Visual regression dengan AI explanation (4 minggu)

- [ ] **M11-1** Screenshot diff (pixel + perceptual)
- [ ] **M11-2** Semantic reason via vision LLM ("Button color changed from green to blue")
- [ ] **M11-3** Threshold tuning per case

## M12 — Mobile testing (5 minggu)

- [ ] **M12-1** `appium-mcp` full bundle
- [ ] **M12-2** Mobile generator strategies (iOS/Android)
- [ ] **M12-3** Device farm integration (BrowserStack adapter)

## M13 — Desktop testing (5 minggu)

- [ ] **M13-1** `computer-use-mcp` integration
- [ ] **M13-2** Generic desktop UI testing (Electron, Win32, macOS)

## M14 — Multi-agent swarm (6 minggu)

- [ ] **M14-1** LangGraph orchestration: Planner + Executor + Critic
- [ ] **M14-2** Higher quality complex test orchestration (multi-step E2E)
- [ ] **M14-3** Inter-agent message bus

## M15 — PR codegen patches (5 minggu)

- [ ] **M15-1** Diagnose `REGRESSION` → AI writes fix → opens PR
- [ ] **M15-2** Requires `auto` autonomy + GitHub integration write scopes
- [ ] **M15-3** Strong audit + review gates (no auto-merge default)

---

# Backlog (post-v2)

- Performance / load testing integration (k6 adapter)
- Compliance pack (SOC 2 controls, ISO 27001 helpers)
- Multi-database (MySQL / SQLite / Mongo) if community demand
- Hosted SaaS spin-off by community
- Marketplace for MCP plugins / prompts / agents
- Federated multi-workspace analytics
- Cross-workspace test case sharing

---

# Cross-cutting notes

- **Setiap milestone punya acceptance + DoD**
- **Setiap PR reference satu acceptance criterion** (`Closes #M2-3`)
- **Dogfood setelah setiap milestone** — Suitest tests Suitest in CI
- **Public roadmap kept in sync via GitHub Projects**
- **Tier gating tested ZERO first** — fitur baru harus jalan di ZERO sebelum LLM enrichment ditambahkan
- **Backwards compatibility**: dari M1 onward, breaking schema changes butuh migration + deprecation note di CHANGELOG

---

## Catatan untuk vibe coder

- **ZERO tier first.** Jangan tulis LLM call sebelum fitur jalan deterministik dulu.
- **Selesaikan satu milestone dulu sebelum lanjut.** Jangan kerja paralel di M2 dan M3.
- **Reference `Suitest.html` mockup setiap kali implementasi UI.**
- **Update doc lain** kalau ada perubahan kontrak ([API.md](./API.md), [DATA_MODEL.md](./DATA_MODEL.md), prompts).
- **Smoke test produk sendiri** setelah setiap milestone. Kalau Suitest tidak bisa test Suitest, kita gagal di vision.
- **Stuck > 2 jam?** Tulis pertanyaan di PR description daripada nebak.
- **Capability gating WAJIB** untuk LLM features — baca [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md).
