# docs/PRODUCT.md

> Vision, personas, dan ruang lingkup tiap layar Suitest. Baca ini dulu sebelum nulis kode untuk fitur baru.

> ℹ️ **VISION doc — describes full v1.0+ product.** Built today: M0–M1e (manual TCM + ZERO-tier deterministic runs + local auth/invite). AI/generators/journeys assuming LLM target M2–M4. Build status: [ROADMAP.md](./ROADMAP.md).
>
> Pivot OSS (2026-05-26): Suitest sekarang **open-source, self-host, BYO-LLM**. Source-of-truth keputusan: [`superpowers/specs/2026-05-26-suitest-oss-pivot-design.md`](./superpowers/specs/2026-05-26-suitest-oss-pivot-design.md).

---

## 1. Vision

> **"QA bukan bottleneck, tapi accelerator. Your stack, your LLM, your data."**

**Suitest adalah open-source, self-hostable testing platform dengan capability tiering: manual TCM jalan tanpa LLM apapun; AI features otomatis aktif ketika user konfigurasi provider LLM mereka sendiri (Anthropic, OpenAI, Gemini, Ollama, llama.cpp, ... — 100+ provider via LiteLLM).**

MCP-as-plugin universal artinya Suitest lebih kuat dari TestSprite: bisa test API (HTTP/GraphQL/gRPC), frontend (Playwright/browser-use), mobile (Appium), database (Postgres/Mongo/MySQL), infrastructure (Kubernetes), atau MCP server apapun yang user pasang. Bukan cuma browser.

**Tiga modal deploy:**

| Tier | Trigger | AI features | TCM + runner |
|------|---------|-------------|--------------|
| **ZERO** | `SUITEST_LLM_PROVIDER=none` atau unset | OFF | ✓ full manual TCM, deterministic runner, MCP plugins, deterministic generators (OpenAPI/Recorder/Crawler), rule-based defect triage |
| **LOCAL** | Ollama / llama.cpp / vLLM / LM Studio | ✓ full, via local model — **air-gapped friendly** | ✓ full |
| **CLOUD** | Anthropic / OpenAI / Gemini / Groq / OpenRouter / Bedrock / Vertex / ... | ✓ full | ✓ full |

Output: **Time-to-Market (TTM)** turun, **release confidence** naik, **QA team focus on strategy**, semuanya tanpa SaaS lock-in dan tanpa kirim data keluar batas regulasi.

Posisi kompetitif (ringkas — lihat memo §1 untuk full matrix):
- **vs TestRail/Zephyr** — Suitest ZERO sudah punya semua yang mereka punya (manual TCM, traceability) PLUS deterministic runner + MCP. Free + OSS.
- **vs Playwright bare** — Suitest pakai Playwright (via MCP) tapi tambahin TCM layer + traceability + multi-target (bukan cuma browser).
- **vs TestSprite** — TestSprite vendor lock-in (their LLM, their cloud). Suitest BYO-LLM, self-host, MCP plugin universal (test API/DB/Infra/Mobile, bukan cuma browser). Tier CLOUD/LOCAL bahkan lebih powerful.

---

## 2. Empat pilar produk

### 🔍 Traceability (bi-directional)
Setiap defect terkait ke test case, setiap test case terkait ke requirement, setiap requirement bisa ditelusuri ke kode source. Tidak ada "tested but unknown what". Bekerja di semua tier — tidak butuh LLM.

### ⚡ Agility
Real-time sync antara CI/CD pipeline, MCP runner, dan dashboard. Hasil run muncul kurang dari 1 detik setelah selesai. Di tier dengan AI: defect terbuka di Jira sebelum engineer membaca log; di ZERO: defect terbuka dengan rule-based triage hint dalam < 5 detik.

### 🤖 Intelligence (tier-aware)
Tier ZERO **tetap pintar**: classifier deterministik (target detection, MCP routing, flaky pattern matcher) + 3 deterministic generators (OpenAPI / Browser Recorder / URL Crawler). Tier LOCAL/CLOUD menambah agentic generation (PRD → cases), semantic URL crawl, MCP tool discovery, AI diagnosis dengan confidence + evidence. Intelligence skala dengan capability, bukan binary on/off.

### 🧩 Pluggability (universal MCP-as-plugin) — **NEW**
Setiap MCP server jadi plugin testing. User pasang MCP server apapun → Suitest pakai. Built-in bundled: `api-mcp`, `playwright-mcp`, `browser-use-mcp`, `postgres-mcp`, `mongo-mcp`, `mysql-mcp`, `graphql-mcp`, `grpc-mcp`, `appium-mcp`, `kubernetes-mcp`. Custom MCP via Settings → Integrations → MCP Servers. Self-host air-gapped. Bring-your-own-LLM via LiteLLM router. Tidak ada vendor lock-in di layer mana pun (TCM, runner, LLM, MCP, storage).

Lihat juga: [MCP_PLUGINS.md](./MCP_PLUGINS.md), [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md).

---

## 3. Personas

### P1 — Maya Putri, QA Lead (primary)
- 6 tahun pengalaman, lead 4-orang QA team di e-commerce mid-size
- Pain: 70% waktu hilang untuk maintain test cases manual yang flaky
- Goal: cut authoring time, focus on test strategy & coverage gaps
- Tier biasa: **CLOUD** (perusahaan udah comfortable dengan Anthropic/OpenAI key)
- Suitest moments: Dashboard, GenerateModal (target-first), Defects auto-sync, hybrid manual+AI flow (Journey F)

### P2 — Rangga Aditya, Backend Engineer (secondary)
- Push code → ingin tahu apakah PR-nya safe untuk merge
- Pain: nunggu QA approve manual, atau push tanpa coverage
- Goal: instant feedback dari CI gating, test case yang cross-cutting (DB + API + frontend)
- Tier biasa: **CLOUD** (CI pipeline punya budget LLM)
- Suitest moments: Test Runs (live logs), Defects (AI diagnosis), Traceability, mixed-MCP E2E (Journey G)

### P3 — Sari Wulandari, Product Manager (tertiary)
- Mau lihat readiness sebelum release Thursday
- Pain: data terpencar antara Jira, Notion, CI
- Goal: one-page snapshot of release health
- Tier biasa: **CLOUD** (cuma viewer, tidak konfigurasi LLM)
- Suitest moments: Dashboard (readiness gauge), Analytics, Traceability

### P4 — Budi Santoso, Platform / SRE Engineer **(NEW — regulated industry)**
- 8 tahun, infra di bank / fintech / healthcare / government — compliance-first
- Pain: SaaS testing tools dilarang policy (PCI-DSS / HIPAA / data sovereignty); QA team pakai Excel + manual click-through
- Goal: self-host testing platform dalam disconnected k8s cluster, **tidak boleh ada outbound traffic apapun**; punya QA team butuh TCM; nanti aktifkan AI via Ollama on-prem
- Tier biasa: **ZERO** awalnya (manual TCM + deterministic), upgrade ke **LOCAL** (Ollama llama3.1 70B on-prem GPU) setelah pilot
- Suitest moments: Air-gapped install via Helm (Journey E), MCP Servers tab (custom kubernetes-mcp pointing internal cluster), zero LLM config first 3 months

### P5 — Lisa Wijaya, Indie Dev / Small Team Lead **(NEW — bootstrap budget)**
- Solo founder atau lead 2-3 orang startup; bootstrap, anti-vendor-lock-in
- Pain: TestRail ($30/user/mo) kemahalan; Playwright bare-bones (no TCM, no traceability, no triage); TestSprite credit-based pricing tidak prediktabel
- Goal: free OSS yang kasih TCM + automation + browser recorder dalam satu app; cuma butuh manual + browser flow
- Tier biasa: **ZERO** seterusnya (LLM key budget gak ada) atau **CLOUD** spot-use (Groq free tier untuk occasional generate)
- Suitest moments: docker-compose 1-command up di laptop, manual TCM authoring, Browser Recorder generator, Crawl URL generator, mungkin Groq spot-use untuk PRD generation kalau ada credit

---

## 4. User journeys utama

### Journey A — Generate dari PRD (P1)
1. Maya buka **Test Cases** → klik **"Generate with AI"**
2. Pilih source: **From requirements** → paste PRD section
3. Klik **Generate** → agen stream 5 test cases dalam ~3 detik
4. Maya review, edit step 5, klik **Add to suite**
5. Test cases tersimpan, otomatis linked ke requirement source

**Success metric:** authoring time turun 80% vs manual

### Journey B — Crawl frontend URL (P1/P2)
1. Maya klik **"Generate with AI"** → **From frontend URL**
2. Input `https://app.suitest.io`, set depth = 3, auth = OAuth
3. Suitest MCP browser explore route, identify interactive flows
4. Agen drafts 12 E2E test cases — Maya pilih 8 untuk di-keep
5. Test cases otomatis berlabel `source: mcp`

**Success metric:** coverage URL routes > 80% tanpa intervensi manual

### Journey C — Test gagal → defect otomatis (P2)
1. Rangga push commit ke `feat/oauth`
2. GitHub Actions trigger Suitest run via webhook
3. Test TC-1045 gagal di step 5 — agen capture artifacts
4. Agen analisis root cause, **buat Jira ticket SUIT-1284** dengan:
   - Stack trace
   - Suggested fix (commit + line number)
   - Linked test case + requirement
5. Slack notif ke `#qa-alerts` channel
6. Rangga buka Jira → 1-click apply patch → re-run via Suitest → green

**Success metric:** time-to-defect-filed < 30 detik dari fail

### Journey D — Release readiness check (P3)
1. Sari buka **Dashboard** Wed sore
2. Lihat **readiness gauge: 86%** — 2 blockers visible
3. Klik **Analytics** → drill into pass rate trend, flaky tests
4. Decision: postpone release atau patch SUIT-1284 hari ini

**Success metric:** release decision dibuat dalam < 5 menit tanpa tanya tim

### Journey E — Air-gapped install (P4) **NEW**
1. Budi pull Helm chart Suitest (`oci://ghcr.io/suitest/suitest`) ke artifact registry internal bank
2. Edit `values.yaml`: `tier=zero`, `embeddings.backend=none`, image pull dari internal mirror, ingress dengan internal CA
3. Deploy di disconnected k8s cluster (no internet): `helm install suitest ./suitest -n testing -f values.yaml`
4. App boot → tier resolution = ZERO; capability `/capabilities` returns AI features off
5. Budi seed dengan OpenAPI specs dari internal repos (curl atau import UI) → deterministic OpenAPI generator produces ~120 contract tests
6. QA team runs contract tests via bundled `api-mcp` → all green
7. (Bulan 3) Tim infra deploy Ollama on internal GPU node → Budi update `values.yaml` `tier=local`, set `llm.provider=ollama`, `llm.base_url=http://ollama.internal:11434` → upgrade tier → AI features activate, masih zero outbound traffic

**Success metric:**
- Install-to-first-test < 30 menit
- Zero outbound network requests (verifikasi via egress policy + audit)
- Compliance auditor satisfied (no data leaves cluster, encrypted at rest, all secrets AES-GCM)

### Journey F — Hybrid manual+AI evolution (P1) **NEW**
1. **Hari 1 (ZERO):** Maya start docker-compose tanpa LLM key. Buka Test Cases → tulis 5 manual test cases untuk login flow. Buka Browser Recorder generator → record 3 checkout flows secara manual → save sebagai test cases (source=`recorder`)
2. Run cases via Playwright MCP — green. Maya happy, traceability working, defect filing manual.
3. **Hari 14:** admin (or Maya) config LLM key via Settings → LLM (Anthropic Claude Sonnet 4.5)
4. Tier resolution updates → CLOUD. Topbar `<TierBadge>` flips ZERO → CLOUD violet. Modal popup: "AI now available. Choose starting mode: [Assist (recommended)] [Semi-auto]" → Maya pick assist.
5. Existing 8 manual cases tetap di place — tidak ada migration, tidak ada break.
6. Maya klik "AI: suggest edge cases" pada salah satu test case → agent generate 10 candidate edge cases in DRAFT status (assist mode = each shown for approval inline)
7. Maya review: approve 7, reject 3. Approved cases saved with source=`ai` linked to parent case via `derivedFromCaseId`.
8. Existing flows + new AI-generated coexist. Run all together → mixed report, AI cases tagged dengan source pill violet.

**Success metric:**
- Incremental adoption: tier upgrade tidak break existing data
- Adoption velocity: AI features dipakai dalam < 5 menit setelah tier upgrade
- Approval friction acceptable: < 30 detik per case review

### Journey G — Mixed-MCP E2E test (P2) **NEW**
1. Rangga butuh test E2E checkout flow yang touch DB + API + frontend
2. Buka Test Cases → New case "Checkout happy path"
3. **Step 1** — action="Seed test order data", mcpProvider=`postgres-mcp`, code (Monaco): `INSERT INTO orders (...) VALUES (...);`
4. **Step 2** — action="Login as test user", mcpProvider=`api-http-mcp`, code: `POST /auth/login {email, password}` → assert 200 + capture token
5. **Step 3** — action="Add item to cart and checkout", mcpProvider=`playwright-mcp`, code: Playwright script `await page.goto(...); await page.click(...);`
6. **Step 4** — action="Verify order created", mcpProvider=`api-http-mcp`, code: `GET /orders/:id` → assert status=`pending`
7. **Step 5** — action="Verify DB state", mcpProvider=`postgres-mcp`, code: `SELECT * FROM orders WHERE id=...` → assert row exists + correct
8. **Step 6** — action="Cleanup", mcpProvider=`postgres-mcp`, code: `DELETE FROM orders WHERE ...`
9. Save case → header shows `Mixed MCP: postgres-mcp + api-http-mcp + playwright-mcp` chip
10. Run case → runner orchestrates 3 MCP providers in sequence, single trace, single artifact bundle, single defect (kalau gagal di mana pun)

**Success metric:**
- Single test case crosses **3 distinct MCP providers** in one trace
- **TestSprite cannot do this** (they're browser-only) — Suitest's killer differentiator
- Setup time per cross-cutting test case: < 10 menit (vs hari-an di Postman + Cypress + manual SQL)

---

## 5. Scope per layar (matching mockup, capability-gated)

> Semua layar respect tier. Capability-gating ditandai dengan ⚙️. Lihat [UI_SPEC.md](./UI_SPEC.md) untuk detail komponen + gating per element.

### 5.1 Dashboard (`/dashboard`)
**Tujuan:** snapshot health workspace dalam < 10 detik.

Komponen:
- 4 KPI cards: Tests run today, Pass rate, Avg duration, Active MCP agents
- Pass rate chart (11-day trend)
- Coverage by suite (progress bars)
- Recent runs (last 5)
- Agent activity feed (last 30 min) — ⚙️ shows manual + recorder activity di ZERO; tambah AI events di LOCAL/CLOUD
- Release readiness card (gauge + checklist)
- ⚙️ **ZERO banner** at top: "Running in manual mode. AI features off. [Enable AI →]" (dismissible)

**Out of scope M1:** custom KPI builder, savable filters.

### 5.2 Inbox (`/inbox`)
**Tujuan:** queue item yang butuh perhatian.

Item types:
- Deploy gate failed (all tiers)
- Manual run failures (all tiers)
- MCP health alerts (all tiers)
- Flaky test promotion request (all tiers — based on stat rules)
- ⚙️ AI-generated test cases pending approval (assist mode only)
- ⚙️ Auto-diagnosis pending review (assist mode only)
- ⚙️ AI fix PR pending merge (auto mode, v1.x)

### 5.3 Test Cases (`/cases`)
**Tujuan:** browse + edit + generate test cases.

Layout:
- Left tree (suites + cases), filter
- Right detail panel: header (badges, actions), metadata, **step editor** with Monaco code field, mcpProvider dropdown, drag-handle reorder
- Top tabs: All / Manual / **AI** (⚙️ hidden di ZERO) / MCP / Failing
- **Split-button** "Generate" — opens **GenerateModal**; dropdown items: Generate (AI ⚙️), Generate from OpenAPI, Record from browser, Crawl URL

**GenerateModal — 5-step target-first flow:**
1. **What are you testing?** — 6 cards: Backend API / Frontend Web / Mobile / Database / Infrastructure / Mixed PRD-driven (⚙️) / Custom MCP
2. **Source input** (depends on target)
3. **MCP provider** auto-selected from routing table, override allowed
4. **Strategy** — Deterministic (default ZERO, always available) / AI-enrich ⚙️ / AI-only ⚙️
5. **Review** — streaming case list dengan checkbox + inline edit; footer cost estimate untuk AI strategies

**Deterministic generators (always available, including ZERO):**
- OpenAPI generator
- Browser Recorder
- Heuristic URL Crawler

### 5.4 Test Runs (`/runs`)
**Tujuan:** live + historical execution.

Layout:
- Top summary: active count, today's pass/fail/duration
- Left: run list with progress bars
- Right: run detail (logs streaming, steps, artifacts, browser preview, network)
- **Per-step MCP provider** displayed di steps list (chip dengan provider name + health dot)
- **Mixed-MCP indicator** di run header kalau ≥2 distinct providers digunakan di satu run
- ⚙️ Per-run footer **`<CostChip>`** showing tokens + USD spent (hidden di ZERO)

### 5.5 Defects (`/defects`)
**Tujuan:** triage failures, sync to Jira (or in-house tracker via MCP plugin).

Per defect card:
- Severity badge, tracker ID, age
- Stack trace
- **Diagnosis section** — capability-aware:
  - ⚙️ **LOCAL/CLOUD:** "Agent Diagnosis" — AI-generated root cause + confidence + evidence (violet card)
  - **ZERO:** "Manual triage needed" — rule-based hint (gray card): "Possible flake — assertion timed out" / "Likely regression — same step passed yesterday" / "Network error — non-2xx response" / "Uncategorized"
- Linked test case + run + component + assignee

### 5.6 Analytics (`/analytics`)
**Tujuan:** trends + diagnostics.

Komponen:
- 3 gauges: Release readiness, Coverage, Pass rate
- Pass rate trend
- Flaky tests list (top 5)
- Execution heatmap (14 days × hours)
- ⚙️ (v1.x) Cost trends per provider, per kind (generation/diagnosis/translation)

### 5.7 Traceability (`/trace`)
**Tujuan:** matrix req ↔ test ↔ defect.

3-column grid yang highlight linked items saat klik requirement. Bekerja di semua tier. Source ingestion di ZERO: paste PRD / import OpenAPI / Linear connector (deterministic). Tambah AI ingestion ⚙️ di LOCAL/CLOUD.

### 5.8 Integrations (`/integrations`)
**Tujuan:** connect/configure external tools.

Tabs:
- All
- CI/CD (GitHub Actions, GitLab, Jenkins, CircleCI)
- Issue Tracker (Jira, Linear, GitHub Issues)
- Notifications (Slack, Discord, Email/SMTP, Webhook)
- **MCP Servers** ⭐ — bundled (read-only) + custom (CRUD), health pills, "Test connection", per-provider tools sub-tab (dev-mode), **routing config drag-drop** per target_kind
- API Discovery (OpenAPI scanner, GraphQL introspection)

Bundled MCP categories (replaces individual entries di pre-pivot doc):
- Browser: `playwright-mcp`, `browser-use-mcp`
- API: `api-http-mcp`, `graphql-mcp`, `grpc-mcp`
- Data: `postgres-mcp`, `mongo-mcp`, `mysql-mcp`
- Infra: `kubernetes-mcp`
- Mobile: `appium-mcp`
- Custom: user-added

### 5.9 Docs & specs (`/docs`)
**Tujuan:** kelola sumber yang dibaca generator untuk produce test cases.

Source types: OpenAPI, PRD paste/Notion, frontend crawl results, Linear user stories.
- ZERO: indexed via FTS (Postgres full-text search) — keyword search only
- ⚙️ LOCAL/CLOUD with embeddings backend != none: semantic search + RAG

### 5.10 Settings → LLM (`/settings/llm`) **NEW**
**Tujuan:** konfigurasi BYO LLM provider; this is THE way to upgrade tier ZERO → LOCAL/CLOUD.

Komponen (lihat UI_SPEC.md §3.7.5):
- Provider dropdown (Cloud / Local grouping via LiteLLM)
- API Key (write-only, AES-GCM at rest)
- Model select (dynamic per provider)
- Advanced: temperature / max_tokens / base_url override
- "Test connection" button (returns latency + first-token-time)
- Save → triggers tier resolve + optional autonomy upgrade prompt
- "Reset to ZERO" destructive

Selalu available di semua tier (justru cara user keluar dari ZERO).

### 5.11 Settings → Automation (`/settings/automation`) **NEW**
**Tujuan:** atur autonomy level per workspace.

Komponen (lihat UI_SPEC.md §3.7.6, AUTONOMY.md):
- Radio 4 level: manual / assist / semi_auto / auto, dengan deskripsi + bullet behavior
- Default per tier: ZERO=manual (locked), LOCAL/CLOUD first session=assist
- Collapsible per-feature overrides (P0-P3 auto-approve matrix, retry policy, auto-close flake)
- Audit log link
- Typed confirmation untuk upgrade assist → semi_auto/auto

⚙️ Hidden di ZERO (autonomy forced manual; no UI choice).

### 5.12 Settings → MCP Routing (`/settings/mcp-routing`) **NEW**
**Tujuan:** atur default MCP provider per target_kind.

Komponen:
- Table: rows = target_kinds (BE_REST, BE_GRAPHQL, BE_GRPC, FE_WEB, FE_MOBILE, DATA, INFRA, CUSTOM)
- Per row: drag-drop ordered list of compatible providers (preferred → fallback)
- First in list = default selected di GenerateModal step 3
- Persist via PUT `/mcp/routing`
- Selalu available di semua tier

---

## 6. Non-functional requirements

| Aspek | Target |
|-------|--------|
| Page load (cold) | < 1.5s TTI (SPA after first paint) |
| FastAPI cold start | < 5s (container ready to serve) |
| WebSocket / SSE latency (run update) | < 500ms |
| Agent generation (5 cases) | < 8s (CLOUD), < 20s (LOCAL on consumer GPU) |
| Deterministic OpenAPI generation (10 ops) | < 1s |
| MCP browser cold start | < 6s |
| Concurrent MCP sessions | 16 per workspace default, configurable |
| **Auth** | OAuth (Google / GitHub) + email/password + Bearer token; **SSO optional via OIDC** (Keycloak, Authentik, Okta) — replaces wajib-SSO assumption |
| Audit log | retensi 1 tahun default, exportable, retention configurable |
| Data residency | **user decides** (self-host, deploy wherever your compliance allows) — no hard-coded region |
| **Air-gapped deploy** | ✓ supported with ZERO tier + bundled MCPs + optional LOCAL via Ollama on-prem |
| Deploy targets | **Helm chart** for k8s production; **docker-compose** for laptop / VPS / single-host |
| Tier resolution | At startup, **cached, immutable per process**; no per-request capability check overhead |
| Encryption at rest | AES-GCM for all stored secrets (LLM keys, MCP secrets, OAuth tokens) |
| Telemetry | OpenTelemetry traces, Prometheus `/metrics`, Sentry optional; no built-in phone-home |

---

## 7. Yang TIDAK dibikin (anti-scope)

- ❌ **Mobile app native** — web responsive saja
- ❌ **Manual test plan / pengujian terstruktur** ala TestLink — fokus automated + lightweight TCM
- ❌ **Performance / load testing** — pakai k6 / Artillery (integrate via webhook)
- ❌ **Security scanning** — pakai Snyk / Trivy / OWASP ZAP (integrate via webhook)
- ❌ **Hosted SaaS version (oleh Suitest team)** — pure OSS self-host only. Community member boleh host their own SaaS untuk pelanggan mereka; kami tidak.
- ❌ **Multi-database (MySQL / SQLite / Mongo) untuk core data layer** — **Postgres only di v1.0** (untuk velocity; pgvector + FTS + JSON semua ada). Note: ini soal Suitest **own data**; test target user boleh apapun (postgres-mcp/mongo-mcp/mysql-mcp untuk testing user DB tetap supported).
- ❌ **Generic agent framework** (autoGPT-style, multi-purpose) — Suitest is **testing-specific**. LangGraph state machines are testing-shaped (generation / execution / diagnosis / conversation), not arbitrary.
- ❌ **TypeScript backend** — Python ekosistem (LiteLLM, LangGraph, MCP Python SDK, browser-use) lebih matang untuk AI/agent work
- ❌ **Next.js SSR FE** — SPA self-host friendly via Vite (no Node runtime di prod, served by nginx)

Note: **Browser Recorder** sebelumnya di anti-scope; sekarang **in-scope** karena via Playwright/browser-use MCP (deterministic generator). Removed dari anti-scope list.

Lihat juga design memo §13 untuk full anti-scope OSS v1.0 rationale.
