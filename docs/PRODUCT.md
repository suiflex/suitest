# docs/PRODUCT.md

> Vision, personas, and scope of each Suitest screen. Read this first before writing code for a new feature.

> ℹ️ **VISION doc — describes full v1.0+ product.** Built today: M0–M1e (manual TCM + ZERO-tier deterministic runs + local auth/invite). AI/generators/journeys assuming LLM target M2–M4. Build status: [ROADMAP.md](./ROADMAP.md).
>
> OSS pivot (2026-05-26): Suitest is now **open-source, self-host, BYO-LLM**. Source-of-truth for the decision: [`superpowers/specs/2026-05-26-suitest-oss-pivot-design.md`](./superpowers/specs/2026-05-26-suitest-oss-pivot-design.md).

---

## 1. Vision

> **"QA is not a bottleneck, but an accelerator. Your stack, your LLM, your data."**

**Suitest is an open-source, self-hostable testing platform with capability tiering: manual TCM works without any LLM; AI features activate automatically once users configure their own LLM provider (Anthropic, OpenAI, Gemini, Ollama, llama.cpp, ... — 100+ providers via LiteLLM).**

Universal MCP-as-plugin means Suitest is more powerful than TestSprite: it can test APIs (HTTP/GraphQL/gRPC), frontends (Playwright/browser-use), mobile (Appium), databases (Postgres/Mongo/MySQL), infrastructure (Kubernetes), or any MCP server the user installs. Not just the browser.

**Three deployment modes:**

| Tier | Trigger | AI features | TCM + runner |
|------|---------|-------------|--------------|
| **ZERO** | `SUITEST_LLM_PROVIDER=none` or unset | OFF | ✓ full manual TCM, deterministic runner, MCP plugins, deterministic generators (OpenAPI/Recorder/Crawler), rule-based defect triage |
| **LOCAL** | Ollama / llama.cpp / vLLM / LM Studio | ✓ full, via local model — **air-gapped friendly** | ✓ full |
| **CLOUD** | Anthropic / OpenAI / Gemini / Groq / OpenRouter / Bedrock / Vertex / ... | ✓ full | ✓ full |

Output: **Time-to-Market (TTM)** goes down, **release confidence** goes up, **QA team focuses on strategy**, all without SaaS lock-in and without sending data across regulatory boundaries.

Competitive positioning (brief — see memo §1 for the full matrix):
- **vs TestRail/Zephyr** — Suitest ZERO already has everything they have (manual TCM, traceability) PLUS deterministic runner + MCP. Free + OSS.
- **vs bare Playwright** — Suitest uses Playwright (via MCP) but adds a TCM layer + traceability + multi-target (not just browser).
- **vs TestSprite** — TestSprite is vendor lock-in (their LLM, their cloud). Suitest is BYO-LLM, self-host, universal MCP plugin (test API/DB/Infra/Mobile, not just browser). The CLOUD/LOCAL tiers are even more powerful.

---

## 2. Four product pillars

### 🔍 Traceability (bi-directional)
Every defect is linked to a test case, every test case is linked to a requirement, every requirement can be traced to source code. No "tested but unknown what". Works in every tier — no LLM required.

### ⚡ Agility
Real-time sync between the CI/CD pipeline, MCP runner, and dashboard. Run results appear less than 1 second after completion. In tiers with AI: defects are opened in Jira before an engineer reads the log; in ZERO: defects are opened with a rule-based triage hint in < 5 seconds.

### 🤖 Intelligence (tier-aware)
The ZERO tier is **still smart**: deterministic classifiers (target detection, MCP routing, flaky pattern matcher) + 3 deterministic generators (OpenAPI / Browser Recorder / URL Crawler). The LOCAL/CLOUD tiers add agentic generation (PRD → cases), semantic URL crawl, MCP tool discovery, AI diagnosis with confidence + evidence. Intelligence scales with capability, not a binary on/off.

### 🧩 Pluggability (universal MCP-as-plugin) — **NEW**
Every MCP server becomes a testing plugin. Users install any MCP server → Suitest uses it. Built-in bundled: `api-mcp`, `playwright-mcp`, `browser-use-mcp`, `postgres-mcp`, `mongo-mcp`, `mysql-mcp`, `graphql-mcp`, `grpc-mcp`, `appium-mcp`, `kubernetes-mcp`. Custom MCP via Settings → Integrations → MCP Servers. Self-host air-gapped. Bring-your-own-LLM via the LiteLLM router. No vendor lock-in at any layer (TCM, runner, LLM, MCP, storage).

See also: [MCP_PLUGINS.md](./MCP_PLUGINS.md), [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md).

---

## 3. Personas

### P1 — Maya Putri, QA Lead (primary)
- 6 years of experience, leads a 4-person QA team at a mid-size e-commerce company
- Pain: 70% of her time is lost maintaining flaky manual test cases
- Goal: cut authoring time, focus on test strategy & coverage gaps
- Typical tier: **CLOUD** (the company is already comfortable with an Anthropic/OpenAI key)
- Suitest moments: Dashboard, GenerateModal (target-first), Defects auto-sync, hybrid manual+AI flow (Journey F)

### P2 — Rangga Aditya, Backend Engineer (secondary)
- Pushes code → wants to know whether his PR is safe to merge
- Pain: waiting for manual QA approval, or pushing without coverage
- Goal: instant feedback from CI gating, cross-cutting test cases (DB + API + frontend)
- Typical tier: **CLOUD** (the CI pipeline has an LLM budget)
- Suitest moments: Test Runs (live logs), Defects (AI diagnosis), Traceability, mixed-MCP E2E (Journey G)

### P3 — Sari Wulandari, Product Manager (tertiary)
- Wants to see readiness before the Thursday release
- Pain: data scattered across Jira, Notion, CI
- Goal: one-page snapshot of release health
- Typical tier: **CLOUD** (viewer only, does not configure the LLM)
- Suitest moments: Dashboard (readiness gauge), Analytics, Traceability

### P4 — Budi Santoso, Platform / SRE Engineer **(NEW — regulated industry)**
- 8 years, infra at a bank / fintech / healthcare / government — compliance-first
- Pain: SaaS testing tools are prohibited by policy (PCI-DSS / HIPAA / data sovereignty); the QA team uses Excel + manual click-through
- Goal: self-host a testing platform inside a disconnected k8s cluster, **no outbound traffic of any kind allowed**; has a QA team that needs TCM; later enable AI via on-prem Ollama
- Typical tier: **ZERO** initially (manual TCM + deterministic), upgrading to **LOCAL** (Ollama llama3.1 70B on-prem GPU) after a pilot
- Suitest moments: Air-gapped install via Helm (Journey E), MCP Servers tab (custom kubernetes-mcp pointing at the internal cluster), zero LLM config for the first 3 months

### P5 — Lisa Wijaya, Indie Dev / Small Team Lead **(NEW — bootstrap budget)**
- Solo founder or lead of a 2-3 person startup; bootstrapped, anti-vendor-lock-in
- Pain: TestRail ($30/user/mo) is too expensive; Playwright is bare-bones (no TCM, no traceability, no triage); TestSprite credit-based pricing is unpredictable
- Goal: free OSS that provides TCM + automation + browser recorder in one app; only needs manual + browser flows
- Typical tier: **ZERO** forever (no LLM key budget) or **CLOUD** spot-use (Groq free tier for occasional generation)
- Suitest moments: docker-compose 1-command up on a laptop, manual TCM authoring, Browser Recorder generator, Crawl URL generator, maybe Groq spot-use for PRD generation if credit is available

---

## 4. Primary user journeys

### Journey A — Generate from PRD (P1)
1. Maya opens **Test Cases** → clicks **"Generate with AI"**
2. Picks source: **From requirements** → pastes a PRD section
3. Clicks **Generate** → the agent streams 5 test cases in ~3 seconds
4. Maya reviews, edits step 5, clicks **Add to suite**
5. Test cases are saved, automatically linked to the source requirement

**Success metric:** authoring time drops 80% vs manual

### Journey B — Crawl frontend URL (P1/P2)
1. Maya clicks **"Generate with AI"** → **From frontend URL**
2. Inputs `https://app.suitest.io`, sets depth = 3, auth = OAuth
3. Suitest MCP browser explores routes, identifies interactive flows
4. The agent drafts 12 E2E test cases — Maya picks 8 to keep
5. Test cases are automatically labeled `source: mcp`

**Success metric:** URL route coverage > 80% without manual intervention

### Journey C — Failed test → automatic defect (P2)
1. Rangga pushes a commit to `feat/oauth`
2. GitHub Actions triggers a Suitest run via webhook
3. Test TC-1045 fails at step 5 — the agent captures artifacts
4. The agent analyzes the root cause, **creates Jira ticket SUIT-1284** with:
   - Stack trace
   - Suggested fix (commit + line number)
   - Linked test case + requirement
5. Slack notification to the `#qa-alerts` channel
6. Rangga opens Jira → 1-click apply patch → re-run via Suitest → green

**Success metric:** time-to-defect-filed < 30 seconds from failure

### Journey D — Release readiness check (P3)
1. Sari opens the **Dashboard** on Wednesday afternoon
2. Sees **readiness gauge: 86%** — 2 blockers visible
3. Clicks **Analytics** → drills into pass rate trend, flaky tests
4. Decision: postpone the release or patch SUIT-1284 today

**Success metric:** release decision made in < 5 minutes without asking the team

### Journey E — Air-gapped install (P4) **NEW**
1. Budi pulls the Suitest Helm chart (`oci://ghcr.io/suitest/suitest`) into the bank's internal artifact registry
2. Edits `values.yaml`: `tier=zero`, `embeddings.backend=none`, images pulled from an internal mirror, ingress with an internal CA
3. Deploys in a disconnected k8s cluster (no internet): `helm install suitest ./suitest -n testing -f values.yaml`
4. App boots → tier resolution = ZERO; capability `/capabilities` returns AI features off
5. Budi seeds with OpenAPI specs from internal repos (curl or the import UI) → the deterministic OpenAPI generator produces ~120 contract tests
6. The QA team runs contract tests via the bundled `api-mcp` → all green
7. (Month 3) The infra team deploys Ollama on an internal GPU node → Budi updates `values.yaml` `tier=local`, sets `llm.provider=ollama`, `llm.base_url=http://ollama.internal:11434` → upgrades the tier → AI features activate, still zero outbound traffic

**Success metric:**
- Install-to-first-test < 30 minutes
- Zero outbound network requests (verified via egress policy + audit)
- Compliance auditor satisfied (no data leaves the cluster, encrypted at rest, all secrets AES-GCM)

### Journey F — Hybrid manual+AI evolution (P1) **NEW**
1. **Day 1 (ZERO):** Maya starts docker-compose without an LLM key. Opens Test Cases → writes 5 manual test cases for the login flow. Opens the Browser Recorder generator → manually records 3 checkout flows → saves them as test cases (source=`recorder`)
2. Runs the cases via Playwright MCP — green. Maya is happy, traceability works, defect filing is manual.
3. **Day 14:** the admin (or Maya) configures an LLM key via Settings → LLM (Anthropic Claude Sonnet 4.5)
4. Tier resolution updates → CLOUD. The topbar `<TierBadge>` flips ZERO → CLOUD violet. Modal popup: "AI now available. Choose starting mode: [Assist (recommended)] [Semi-auto]" → Maya picks assist.
5. The existing 8 manual cases stay in place — no migration, no breakage.
6. Maya clicks "AI: suggest edge cases" on one of the test cases → the agent generates 10 candidate edge cases in DRAFT status (assist mode = each shown for approval inline)
7. Maya reviews: approves 7, rejects 3. Approved cases are saved with source=`ai` linked to the parent case via `derivedFromCaseId`.
8. Existing flows + new AI-generated ones coexist. Run all together → mixed report, AI cases tagged with a violet source pill.

**Success metric:**
- Incremental adoption: tier upgrade does not break existing data
- Adoption velocity: AI features used within < 5 minutes after the tier upgrade
- Approval friction acceptable: < 30 seconds per case review

### Journey G — Mixed-MCP E2E test (P2) **NEW**
1. Rangga needs an E2E checkout flow test that touches DB + API + frontend
2. Opens Test Cases → New case "Checkout happy path"
3. **Step 1** — action="Seed test order data", mcpProvider=`postgres-mcp`, code (Monaco): `INSERT INTO orders (...) VALUES (...);`
4. **Step 2** — action="Login as test user", mcpProvider=`api-http-mcp`, code: `POST /auth/login {email, password}` → assert 200 + capture token
5. **Step 3** — action="Add item to cart and checkout", mcpProvider=`playwright-mcp`, code: Playwright script `await page.goto(...); await page.click(...);`
6. **Step 4** — action="Verify order created", mcpProvider=`api-http-mcp`, code: `GET /orders/:id` → assert status=`pending`
7. **Step 5** — action="Verify DB state", mcpProvider=`postgres-mcp`, code: `SELECT * FROM orders WHERE id=...` → assert row exists + correct
8. **Step 6** — action="Cleanup", mcpProvider=`postgres-mcp`, code: `DELETE FROM orders WHERE ...`
9. Saves the case → header shows a `Mixed MCP: postgres-mcp + api-http-mcp + playwright-mcp` chip
10. Runs the case → the runner orchestrates 3 MCP providers in sequence, single trace, single artifact bundle, single defect (if it fails anywhere)

**Success metric:**
- Single test case crosses **3 distinct MCP providers** in one trace
- **TestSprite cannot do this** (they're browser-only) — Suitest's killer differentiator
- Setup time per cross-cutting test case: < 10 minutes (vs days in Postman + Cypress + manual SQL)

---

## 5. Scope per screen (matching mockup, capability-gated)

> All screens respect the tier. Capability-gating is marked with ⚙️. See [UI_SPEC.md](./UI_SPEC.md) for component details + per-element gating.

### 5.1 Dashboard (`/dashboard`)
**Purpose:** snapshot of workspace health in < 10 seconds.

Components:
- 4 KPI cards: Tests run today, Pass rate, Avg duration, Active MCP agents
- Pass rate chart (11-day trend)
- Coverage by suite (progress bars)
- Recent runs (last 5)
- Agent activity feed (last 30 min) — ⚙️ shows manual + recorder activity in ZERO; adds AI events in LOCAL/CLOUD
- Release readiness card (gauge + checklist)
- ⚙️ **ZERO banner** at top: "Running in manual mode. AI features off. [Enable AI →]" (dismissible)

**Out of scope M1:** custom KPI builder, savable filters.

### 5.2 Inbox (`/inbox`)
**Purpose:** queue of items that need attention.

Item types:
- Deploy gate failed (all tiers)
- Manual run failures (all tiers)
- MCP health alerts (all tiers)
- Flaky test promotion request (all tiers — based on stat rules)
- ⚙️ AI-generated test cases pending approval (assist mode only)
- ⚙️ Auto-diagnosis pending review (assist mode only)
- ⚙️ AI fix PR pending merge (auto mode, v1.x)

### 5.3 Test Cases (`/cases`)
**Purpose:** browse + edit + generate test cases.

Layout:
- Left tree (suites + cases), filter
- Right detail panel: header (badges, actions), metadata, **step editor** with Monaco code field, mcpProvider dropdown, drag-handle reorder
- Top tabs: All / Manual / **AI** (⚙️ hidden in ZERO) / MCP / Failing
- **Split-button** "Generate" — opens the **GenerateModal**; dropdown items: Generate (AI ⚙️), Generate from OpenAPI, Record from browser, Crawl URL

**GenerateModal — 5-step target-first flow:**
1. **What are you testing?** — 6 cards: Backend API / Frontend Web / Mobile / Database / Infrastructure / Mixed PRD-driven (⚙️) / Custom MCP
2. **Source input** (depends on target)
3. **MCP provider** auto-selected from the routing table, override allowed
4. **Strategy** — Deterministic (default ZERO, always available) / AI-enrich ⚙️ / AI-only ⚙️
5. **Review** — streaming case list with checkboxes + inline edit; footer cost estimate for AI strategies

**Deterministic generators (always available, including ZERO):**
- OpenAPI generator
- Browser Recorder
- Heuristic URL Crawler

### 5.4 Test Runs (`/runs`)
**Purpose:** live + historical execution.

Layout:
- Top summary: active count, today's pass/fail/duration
- Left: run list with progress bars
- Right: run detail (logs streaming, steps, artifacts, browser preview, network)
- **Per-step MCP provider** displayed in the steps list (chip with provider name + health dot)
- **Mixed-MCP indicator** in the run header when ≥2 distinct providers are used in one run
- ⚙️ Per-run footer **`<CostChip>`** showing tokens + USD spent (hidden in ZERO)

### 5.5 Defects (`/defects`)
**Purpose:** triage failures, sync to Jira (or an in-house tracker via MCP plugin).

Per defect card:
- Severity badge, tracker ID, age
- Stack trace
- **Diagnosis section** — capability-aware:
  - ⚙️ **LOCAL/CLOUD:** "Agent Diagnosis" — AI-generated root cause + confidence + evidence (violet card)
  - **ZERO:** "Manual triage needed" — rule-based hint (gray card): "Possible flake — assertion timed out" / "Likely regression — same step passed yesterday" / "Network error — non-2xx response" / "Uncategorized"
- Linked test case + run + component + assignee

### 5.6 Analytics (`/analytics`)
**Purpose:** trends + diagnostics.

Components:
- 3 gauges: Release readiness, Coverage, Pass rate
- Pass rate trend
- Flaky tests list (top 5)
- Execution heatmap (14 days × hours)
- ⚙️ (v1.x) Cost trends per provider, per kind (generation/diagnosis/translation)

### 5.7 Traceability (`/trace`)
**Purpose:** matrix req ↔ test ↔ defect.

3-column grid that highlights linked items when a requirement is clicked. Works in every tier. Source ingestion in ZERO: paste PRD / import OpenAPI / Linear connector (deterministic). Adds AI ingestion ⚙️ in LOCAL/CLOUD.

### 5.8 Integrations (`/integrations`)
**Purpose:** connect/configure external tools.

Tabs:
- All
- CI/CD (GitHub Actions, GitLab, Jenkins, CircleCI)
- Issue Tracker (Jira, Linear, GitHub Issues)
- Notifications (Slack, Discord, Email/SMTP, Webhook)
- **MCP Servers** ⭐ — bundled (read-only) + custom (CRUD), health pills, "Test connection", per-provider tools sub-tab (dev-mode), **routing config drag-drop** per target_kind
- API Discovery (OpenAPI scanner, GraphQL introspection)

Bundled MCP categories (replaces the individual entries in the pre-pivot doc):
- Browser: `playwright-mcp`, `browser-use-mcp`
- API: `api-http-mcp`, `graphql-mcp`, `grpc-mcp`
- Data: `postgres-mcp`, `mongo-mcp`, `mysql-mcp`
- Infra: `kubernetes-mcp`
- Mobile: `appium-mcp`
- Custom: user-added

### 5.9 Docs & specs (`/docs`)
**Purpose:** manage the sources the generators read to produce test cases.

Source types: OpenAPI, PRD paste/Notion, frontend crawl results, Linear user stories.
- ZERO: indexed via FTS (Postgres full-text search) — keyword search only
- ⚙️ LOCAL/CLOUD with embeddings backend != none: semantic search + RAG

### 5.10 Settings → LLM (`/settings/llm`) **NEW**
**Purpose:** configure the BYO LLM provider; this is THE way to upgrade tier ZERO → LOCAL/CLOUD.

Components (see UI_SPEC.md §3.7.5):
- Provider dropdown (Cloud / Local grouping via LiteLLM)
- API Key (write-only, AES-GCM at rest)
- Model select (dynamic per provider)
- Advanced: temperature / max_tokens / base_url override
- "Test connection" button (returns latency + first-token-time)
- Save → triggers tier resolve + optional autonomy upgrade prompt
- "Reset to ZERO" destructive

Always available in every tier (it is precisely how users get out of ZERO).

### 5.11 Settings → Automation (`/settings/automation`) **NEW**
**Purpose:** set the autonomy level per workspace.

Components (see UI_SPEC.md §3.7.6, AUTONOMY.md):
- Radio with 4 levels: manual / assist / semi_auto / auto, with descriptions + behavior bullets
- Default per tier: ZERO=manual (locked), LOCAL/CLOUD first session=assist
- Collapsible per-feature overrides (P0-P3 auto-approve matrix, retry policy, auto-close flake)
- Audit log link
- Typed confirmation for upgrading assist → semi_auto/auto

⚙️ Hidden in ZERO (autonomy forced to manual; no UI choice).

### 5.12 Settings → MCP Routing (`/settings/mcp-routing`) **NEW**
**Purpose:** set the default MCP provider per target_kind.

Components:
- Table: rows = target_kinds (BE_REST, BE_GRAPHQL, BE_GRPC, FE_WEB, FE_MOBILE, DATA, INFRA, CUSTOM)
- Per row: drag-drop ordered list of compatible providers (preferred → fallback)
- First in list = default selected in GenerateModal step 3
- Persist via PUT `/mcp/routing`
- Always available in every tier

---

## 6. Non-functional requirements

| Aspect | Target |
|-------|--------|
| Page load (cold) | < 1.5s TTI (SPA after first paint) |
| FastAPI cold start | < 5s (container ready to serve) |
| WebSocket / SSE latency (run update) | < 500ms |
| Agent generation (5 cases) | < 8s (CLOUD), < 20s (LOCAL on consumer GPU) |
| Deterministic OpenAPI generation (10 ops) | < 1s |
| MCP browser cold start | < 6s |
| Concurrent MCP sessions | 16 per workspace default, configurable |
| **Auth** | OAuth (Google / GitHub) + email/password + Bearer token; **SSO optional via OIDC** (Keycloak, Authentik, Okta) — replaces the mandatory-SSO assumption |
| Audit log | 1 year retention by default, exportable, retention configurable |
| Data residency | **user decides** (self-host, deploy wherever your compliance allows) — no hard-coded region |
| **Air-gapped deploy** | ✓ supported with ZERO tier + bundled MCPs + optional LOCAL via Ollama on-prem |
| Deploy targets | **Helm chart** for k8s production; **docker-compose** for laptop / VPS / single-host |
| Tier resolution | At startup, **cached, immutable per process**; no per-request capability check overhead |
| Encryption at rest | AES-GCM for all stored secrets (LLM keys, MCP secrets, OAuth tokens) |
| Telemetry | OpenTelemetry traces, Prometheus `/metrics`, Sentry optional; no built-in phone-home |

---

## 7. What we will NOT build (anti-scope)

- ❌ **Native mobile app** — web responsive only
- ❌ **Manual test plans / structured testing** à la TestLink — focus on automated + lightweight TCM
- ❌ **Performance / load testing** — use k6 / Artillery (integrate via webhook)
- ❌ **Security scanning** — use Snyk / Trivy / OWASP ZAP (integrate via webhook)
- ❌ **Hosted SaaS version (by the Suitest team)** — pure OSS self-host only. Community members may host their own SaaS for their customers; we won't.
- ❌ **Multi-database (MySQL / SQLite / Mongo) for the core data layer** — **Postgres only in v1.0** (for velocity; pgvector + FTS + JSON are all there). Note: this is about Suitest's **own data**; user test targets can be anything (postgres-mcp/mongo-mcp/mysql-mcp for testing user DBs remain supported).
- ❌ **Generic agent framework** (autoGPT-style, multi-purpose) — Suitest is **testing-specific**. LangGraph state machines are testing-shaped (generation / execution / diagnosis / conversation), not arbitrary.
- ❌ **TypeScript backend** — the Python ecosystem (LiteLLM, LangGraph, MCP Python SDK, browser-use) is more mature for AI/agent work
- ❌ **Next.js SSR FE** — SPA self-host friendly via Vite (no Node runtime in prod, served by nginx)

Note: the **Browser Recorder** was previously in the anti-scope; it is now **in-scope** because it works via Playwright/browser-use MCP (deterministic generator). Removed from the anti-scope list.

See also design memo §13 for the full anti-scope OSS v1.0 rationale.
