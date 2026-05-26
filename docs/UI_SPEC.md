# docs/UI_SPEC.md

> Spesifikasi komponen frontend sesuai mockup di `Suitest.html`. Pakai dokumen ini sebagai checklist saat implementing screen baru. **Setiap claim visual di sini di-back oleh mockup** — kalau ragu, buka mockup.

---

## 1. Foundation

### 1.1 Tech setup
- **Vite 6 + React 19 + TS + TanStack Router** (SPA, self-host friendly — bukan Next.js lagi)
- **TanStack Query** untuk server state, **Zustand** untuk global UI state (sidebar, AI panel, capabilities, tier)
- **`@ai-sdk/react` + `assistant-ui`** untuk AI streaming chat (thread, tool render, provider-agnostic)
- **Monaco Editor** untuk editing `step.code` (TS/Python), **dnd-kit** untuk step reordering
- **Recharts** untuk charts, optional **Tremor** primitives untuk dashboard widgets
- Tailwind 4 dengan custom config (tokens di section 1.3)
- shadcn/ui untuk primitives
- Lucide React untuk icons
- Geist + Geist Mono (self-hosted via `@fontsource/geist` — no Google Fonts CDN dependency)
- Build output: `dist/` static, served by nginx di Docker / Helm; backend FastAPI via reverse proxy `/api/*` + `/ws`

Lihat juga: [DEPLOYMENT.md](../DEPLOYMENT.md), [ARCHITECTURE.md](../ARCHITECTURE.md).

### 1.2 App layout
Persistent shell pada semua authenticated routes:

```
┌──────────┬─────────────────────────────────────┬──────────────┐
│          │  Topbar (crumbs · search · actions) │              │
│ Sidebar  ├─────────────────────────────────────┤   AI Panel   │
│  224px   │                                     │    380px     │
│          │           Main content              │              │
│          │                                     │              │
└──────────┴─────────────────────────────────────┴──────────────┘
       1440px design width, 900px design height
```

Layout grid: `grid-template-columns: 224px 1fr 380px` di root `.app`.

Responsive: di bawah 1280px lebar, AI panel jadi collapsible overlay (state via Zustand store `useAiPanel`). Sidebar tetap fixed.

### 1.3 Design tokens

Defined di `apps/web/src/styles/globals.css`:

```css
:root {
  --bg-base: #0a0a0a;
  --bg-elev-1: #111111;
  --bg-elev-2: #161616;
  --bg-elev-3: #1c1c1c;
  --bg-hover: #1f1f1f;

  --border-subtle: #1c1c1c;
  --border: #262626;
  --border-strong: #333;

  --fg-1: #fafafa;   /* primary text */
  --fg-3: #a3a3a3;   /* secondary */
  --fg-4: #737373;   /* muted */
  --fg-5: #525252;   /* placeholder */

  --accent: #4ade80;          /* primary action, pass */
  --accent-fg: #052e16;       /* text on accent */
  --accent-dim: rgba(74,222,128,.12);

  --red: #f87171;             /* fail */
  --amber: #fbbf24;           /* warn, flaky */
  --blue: #60a5fa;            /* info, running */
  --violet: #a78bfa;          /* AI-generated */

  --radius: 6px;
  --radius-lg: 8px;
}
```

Tailwind classes equivalent (kalau pakai shadcn): `bg-background`, `text-foreground`, `border-border`, `text-muted-foreground`, dst — map via `tailwind.config.ts`.

### 1.4 Typography scale

| Use case | Class | Detail |
|----------|-------|--------|
| Page title | `text-[18px] font-semibold tracking-[-.01em]` | "Dashboard", "Test Cases" |
| Card title | `text-[13px] font-semibold` | Header dalam Card |
| Body | `text-[13px]` | Default — perhatikan: **bukan** 14px |
| Small | `text-[12.5px]` | Metadata, table cells |
| Tiny | `text-[11px] text-muted-foreground` | Timestamps, eyebrows |
| Eyebrow | `text-[11px] uppercase tracking-[0.07em] text-[var(--fg-5)] font-medium` | Section labels |
| Code/ID | `font-mono text-[11.5px]` | Mono untuk all IDs, code, paths |

---

### 1.5 Capability-gated rendering

Suitest jalan di 3 tier (ZERO / LOCAL / CLOUD — lihat [CAPABILITY_TIERS.md](../CAPABILITY_TIERS.md)). UI **tidak boleh** asumsi AI tersedia. Semua afford­ance AI lewat capability gate.

**App boot:**
```ts
// src/lib/capabilities.ts
const res = await fetch('/api/v1/capabilities'); // no auth required
useCapabilities.setState({ tier, provider, model, features, autonomy });
```

**Wrapper komponen:**
```tsx
<Gated feature="ai_generation">
  <GenerateButton />
</Gated>

// dengan fallback placeholder:
<Gated feature="ai_generation" fallback={<DisabledPlaceholder reason="LLM not configured" />}>
  <GenerateButton />
</Gated>
```

**Hook untuk inline conditional:**
```tsx
const canDiagnose = useFeatureEnabled('ai_diagnosis');
return canDiagnose ? <AgentDiagnosisCard /> : <ManualTriageCard />;
```

**Capability change:** subscribe WS event `capability.changed` (broadcast saat admin update LLM config) → refetch `/capabilities` → trigger re-render of all `<Gated>` consumers (Zustand subscription).

**Features keys:** `ai_generation`, `ai_diagnosis`, `ai_translation` (action→code), `ai_chat`, `autonomy_assist`, `autonomy_semi_auto`, `autonomy_auto`, `embeddings_semantic`. Deterministic stuff (manual TCM, OpenAPI generator, Recorder, Crawler, MCP runner) **tidak** di-gate — selalu enabled.

### 1.6 Tier badge (topbar)

Chip kecil di top-right Topbar, tepat sebelum search palette trigger:

| Tier | Tampilan | Color token |
|------|----------|-------------|
| ZERO | `ZERO` | gray `bg-elev-2 text-fg-3` |
| LOCAL | `LOCAL · ollama:llama3.1` | blue `bg-blue/10 text-blue border-blue/20` |
| CLOUD | `CLOUD · anthropic:claude-sonnet-4-5` | violet `bg-violet/10 text-violet border-violet/20` |

Klik → Popover (shadcn) berisi:
- Tier name + provider + model
- Latency (last `/llm-config/test` result, mono)
- Token spend last 24h (kalau ada cost tracking)
- "Configure" link → `/settings/llm`
- "Switch autonomy" link → `/settings/automation`

Component: `<TierBadge />` (lihat section 4.10).

### 1.7 Banners (system-level messages)

Banner area di bawah Topbar, di atas Main content. Maks 1 banner kelihatan sekaligus; lainnya antri.

| Banner | Kondisi | Tone | Behavior |
|--------|---------|------|----------|
| ZERO manual mode | tier=ZERO, never dismissed (per-user persisted in localStorage) | info gray | "Running in manual mode. AI features off. [Enable AI →]" — link ke `/settings/llm`. Dismissible. |
| Autonomy upgrade prompt | tier baru upgrade dari ZERO → LOCAL/CLOUD, first session | violet modal | "AI now available. Choose starting mode: [Assist (recommended)] [Semi-auto]". Modal, dismiss = stays in `manual`. |
| LLM provider unreachable | last 3 calls fail | red persistent | "LLM provider unreachable. Last successful call N min ago. [Open Settings]" — non-dismissible until resolved. |
| MCP provider down | per-provider health check fail | amber | Tidak global — muncul di Integrations page sebagai per-card warning + topbar health dot indicator. |

Banner state managed di Zustand store `useBanners` — sources: capability change events, `/health` polling, WS events.

---

## 2. Shell components

### 2.1 Sidebar (`components/shell/Sidebar.tsx`)

Width 224px, full height, dark background, no scroll except `nav` body section.

**Sections (top → bottom):**
1. **Brand**: `suitest` logo (mono, bold "test" portion accent green) + notif bell button
2. **Workspace picker**: avatar + name + chevron, klik buka WorkspaceSwitcher popover
3. **Nav** (scrollable): grouped — Workspace / Testing / Insights / Config
4. **User footer**: avatar + name + role + settings icon

**Nav items**: icon (14px) + label + badge (count or live dot).

State: `route` derived from `usePathname()`. Active item: bg `var(--bg-elev-2)`, icon tinted accent.

**Live dot** untuk "Test Runs": animated `pulse 2s infinite` saat ada active run. Subscribe via WS `workspace:<id>` topic, listen `run.started` / `run.completed`.

### 2.2 Topbar (`components/shell/Topbar.tsx`)

Height 47px, bottom border `var(--border-subtle)`.

**Left:** breadcrumbs (`Workspace › Section › Detail`). Last segment in `text-foreground` font-medium, others muted.

**Right:** search palette trigger (220px wide, ⌘K hint), help/notif icons, "+ New" button.

Search palette = shadcn Command Dialog yang mencakup quick actions: navigate, run test, ask agent.

### 2.3 AiPanel (`components/shell/AiPanel.tsx`)

Width 380px, left border `var(--border-subtle)`, background `var(--bg-elev-1)`.

**Capability gating:**
- **ZERO tier**: AiPanel **hidden entirely**. Root grid jadi `224px 1fr` (sidebar + main full-bleed). Main content dapat ekstra `~220px` width (Tailwind responsive class swap, atau `useCapabilities()` di root layout component). Tidak ada placeholder, tidak ada empty AI section.
- **LOCAL/CLOUD + autonomy=manual**: panel **read-only history** — composer hidden / disabled with tooltip ("Switch to assist mode to enable AI composer"). Thread tetap kelihatan supaya user bisa baca audit log past sessions (kalau ada).
- **LOCAL/CLOUD + autonomy=assist**: composer enabled. Setiap agentic tool call yg butuh side-effect (MCP call, file defect, write code) muncul sebagai **approval card inline** di thread: "Agent wants to call `mcp.api.request POST /orders` — [Approve] [Reject] [Edit args]". Streaming pause sampai user pilih.
- **LOCAL/CLOUD + autonomy=semi_auto / auto**: approval card hanya untuk P0/P1 high-risk; lain auto-execute dengan trace card (no buttons, just status).

**Sections:**
1. **Header** (47px): agent avatar with green status dot, name "Suitest Agent", subtitle shows `{provider}:{model} · {autonomy_level} · N sessions`, history + more icons. Includes `<AutonomyIndicator />` chip.
2. **Thread** (scrollable): chronological messages — built on `assistant-ui` `<Thread>` component, customized untuk dark theme tokens via CSS variable override (`--aui-bg`, `--aui-fg-1`, dll → map ke design tokens kita)
3. **Composer** (sticky bottom): mode selector + textarea + attach buttons + send (atau cancel saat streaming)

**Message types:**
- Text message dengan role pill (USER / AGENT) — streaming via SSE
- Inline tool call card (terminal-style, mono, with status + duration + provider name `via playwright-mcp`)
- Inline **approval card** (assist mode only): tool name + args JSON preview + Approve/Reject/Edit
- Suggestion chips (clickable, prefix icon)

**Mode tabs:** Agent (default action), Generate (test cases), Ask (RAG-only Q&A — fallback FTS kalau embeddings backend=`none`).

**Streaming transport:**
- **SSE preferred untuk token streaming** (simpler, no WS reconnect logic, native browser `EventSource`). Endpoint: `POST /agent/sessions/:id/messages` → SSE stream of `text-delta` events.
- **WS untuk tool call events** + multi-client sync (mis. session running di tab lain): subscribe room `agent-session:<id>` via FastAPI WebSocket. Events: `tool.requested`, `tool.executed`, `tool.failed`, `approval.required`.
- **Cancel button** saat streaming — `POST /agent/sessions/:id/cancel` → server abort LangGraph node + close SSE.

**Persistence:** thread per route — saat user nav, panel switch ke session berbeda (mostly read-only memory of prior conversations).

Lihat juga: [AI_AGENT.md](../AI_AGENT.md), [AUTONOMY.md](../AUTONOMY.md).

---

## 3. Screen specs

### 3.1 Dashboard

Path: `/dashboard`. Component: `app/(app)/dashboard/page.tsx`.

**Page header:** title "Dashboard" + green "All systems healthy" badge. Subtitle: "Selamat siang, {firstName} — here's your test quality snapshot." Right actions: "Last 7 days" filter, "Run gating suite" primary button.

**Body sections** (vertically stacked, gap 18px):

1. **KPI grid** (4 columns): tests run today, pass rate, avg duration, active MCP agents. Each card 14px padding, KPI value 24px tabular nums, delta with arrow icon.

2. **Two-column grid:**
   - Pass rate chart (line chart, 11-day window, accent green stroke, gradient fill)
   - Coverage by suite (progress bars per suite)

3. **Two-column grid:**
   - Recent runs (mini list of 5 runs with status pills)
   - Agent activity feed (last 30 min, colored icon per type)

4. **Release readiness card:** gauge (120px circle) + 5-item checklist (✓ / ✗)

**Data:**
- `GET /api/v1/analytics/kpis?period=7d`
- `GET /api/v1/analytics/pass-rate?period=11d`
- `GET /api/v1/analytics/coverage`
- `GET /api/v1/runs?limit=5`
- `GET /api/v1/audit-logs?action=agent.*&limit=5`
- `GET /api/v1/analytics/readiness`

### 3.2 Test Cases

Path: `/cases`. Component: `src/routes/(app)/cases.tsx` (TanStack Router).

**Top tabs:** All · Manual · AI-generated · MCP · Failing — with counts. **AI-generated tab hidden di ZERO** (no AI-source cases will exist). Filter button + **split-button** "Generate" primary CTA.

**Split-button "Generate" (replaces lone "Generate with AI"):**

Main click → opens GenerateModal (defaults to deterministic strategy).

Dropdown chevron → menu items:
- `✨ Generate (AI)` — opens GenerateModal step 4 strategy=`ai_only`. **Disabled di ZERO** dengan `<DisabledTooltip reason="LLM not configured. Settings → LLM" />`.
- `{ } Generate from OpenAPI` — opens GenerateModal step 2 source=`openapi`, strategy locked to `deterministic`. **Always available** (also in ZERO).
- `● Record from browser` — opens Browser Recorder flow (deterministic). **Always available**.
- `🔗 Crawl URL` — opens heuristic URL crawler. **Always available**.

Di ZERO: split-button **tetap kelihatan dan usable** untuk 3 deterministic generators; hanya item "Generate (AI)" yang disabled. Jangan sembunyikan seluruh CTA — itu bikin user kira fitur generate hilang.

Lihat juga: [GENERATORS.md](../GENERATORS.md).

**Layout:** split-pane.
- Left 280px: filter input + tree (suite headers + case items)
- Right flex: detail panel

**Tree item** (mono font, but case name in sans):
- Status dot (color per case status)
- ID `TC-1045`
- Name
- Source pill (MANUAL/AI/MCP/IMPORT) — AI = violet bg, MCP = blue bg

**Detail panel sections:**
1. Toolbar: ID badge, status badge, priority badge, last-run metadata, actions (Compare, Edit with AI, Run now)
2. Header: suite eyebrow, large title (22px), description
3. Metadata card: 5 fields (Owner, Suite, Generated by, Source, Avg duration) di card layout
4. Steps section: heading + "Add step" + "AI: suggest edge cases" buttons, then numbered step cards
5. **Agent insight callout**: violet-tinted card with sparkle icon + diagnosis text

**Step card:** numbered circle + action + expected (mono, with green left border + "Expected" label) + optional code snippet

**Data:**
- `GET /api/v1/suites?projectId={current}`
- `GET /api/v1/test-cases?suiteId=...`
- `GET /api/v1/test-cases/:id` (selected detail)

#### 3.2.1 GenerateModal (Dialog) — legacy 4-step flow

> Catatan: flow ini di-superseded oleh **3.2.1.5** (target-first 5-step). Section ini disimpan sebagai referensi historis dari mockup `Suitest.html`; **implementasi v1.0 pakai 3.2.1.5**.

shadcn Dialog, max-w 880px, max-h 88vh. (Sections 1-5 dan generation flow lama — lihat git history kalau perlu.)

#### 3.2.1.5 GenerateModal — target-first 5-step flow (v1.0)

shadcn Dialog, max-w 920px, max-h 90vh. Stepper indicator di header.

**Step 1: What are you testing?** — 6 cards grid (3×2):

| Card | Target kind | Default MCP |
|------|-------------|-------------|
| 🧩 Backend API | `BE_REST` / `BE_GRAPHQL` / `BE_GRPC` (auto-detect dari source) | `api-mcp` |
| 🌐 Frontend Web | `FE_WEB` | `playwright-mcp` |
| 📱 Mobile | `FE_MOBILE` | `appium-mcp` |
| 🗄️ Database | `DATA` | `postgres-mcp` |
| ☁️ Infrastructure | `INFRA` | `kubernetes-mcp` |
| ✨ Mixed PRD-driven | multi-target dari PRD parsing | dynamic per step |
| 🔌 Custom MCP | `CUSTOM` | user-picked |

**ZERO behavior:** "Mixed PRD-driven" dan AI-driven cards **grayed out** dengan `<DisabledTooltip reason="Requires LLM. Settings → LLM" />`. Backend/Frontend/DB/Infra/Custom MCP tetap available untuk deterministic generators.

Active card = green-tinted with accent border.

**Step 2: Source input** — content depends on target chosen di step 1:
- Backend API → OpenAPI URL / spec paste / GraphQL schema URL
- Frontend Web → URL + depth + auth method (none / cookie / bearer / OAuth)
- Mobile → APK upload / iOS bundle / Appium capabilities
- Database → connection string (read-only role enforced) + schema picker
- Infrastructure → kubeconfig namespace + resource selector
- Mixed PRD → markdown/text textarea (paste PRD/user story)
- Custom MCP → MCP server URL + tool discovery preview

**Step 3: MCP provider** — auto-selected dari routing table (Settings → MCP Routing). "Change" button → picker showing registered providers **compatible with target_kind** (filtered, sorted by health + recency). User can also add custom inline (link to Integrations → MCP Servers → Add Custom).

Display: `<McpProviderPill>` per provider with health dot + transport (stdio/SSE/WS) + version.

**Step 4: Generation strategy** — radio:
- ⚙️ **Deterministic** (default in ZERO; always available) — uses generator yg cocok dengan target (OpenAPI/Recorder/Crawler). No LLM call.
- ✨ **AI-enrich** (requires LLM) — deterministic baseline + LLM additions (edge cases, negative paths, fuzz hints).
- 🤖 **AI-only** (requires LLM) — full LLM-driven (PRD parsing, semantic crawl, MCP tool exploration).

Strategy radio non-`Deterministic` di-disable dengan tooltip di ZERO. Default selection adapts to tier: ZERO=`deterministic`, CLOUD/LOCAL=`ai_enrich`.

**Step 5: Review & approve** — streaming preview list of generated cases. Each row:
- Checkbox (default checked)
- ID placeholder, title (inline-editable on click)
- Source pill (DETERMINISTIC / AI / MIXED)
- Step count + estimated runtime
- "Expand" → see full steps in side drawer

User dapat uncheck unwanted, edit titles inline. Hitting "Add N to suite" → POST `/test-cases` batch.

**Footer:**
- Left: **cost estimate chip** untuk `ai_only` / `ai_enrich` — calculated from LiteLLM model pricing × estimated tokens. Format: `~$0.04 · ~4.2k tokens` (`<CostChip>` component). ZERO + Deterministic → hide.
- Right: Cancel + Generate (primary) / "Add N to suite" (saat step 5 ada hasil)

**Generation flow:**
1. Click Generate → POST `/agent/generate/cases` body includes `{ targetKind, source, mcpProvider, strategy }` (SSE)
2. Each `case` SSE event prepends to step 5 list with slide-in animation
3. After `complete` event, replace Generate button with "Add N to suite"
4. User unchecks unwanted, clicks Add → POST `/test-cases` batch endpoint with `agentSessionId` (untuk reproducibility trace)

Capability check upfront: kalau strategy ∈ {`ai_only`, `ai_enrich`} tapi tier=ZERO, button "Generate" di-disable + show banner inline "AI strategy requires LLM config — switch to Deterministic or [Configure LLM]".

#### 3.2.2 Step editor

Component: `src/components/cases/StepEditor.tsx`. Renders per-step card di Detail panel section 4 (steps section), replaces simple "step card" dari layout lama.

**Per-step fields:**
- `action` — text (single-line input, natural language: "Login dengan user X")
- `expected` — text (multi-line, monospaced)
- `code` — **Monaco editor** (TS/Python), 6-line min height, syntax highlight by `mcpProvider.language` hint, autoformat on blur
- `mcpProvider` — dropdown of registered providers compatible with `targetKind`
- `targetKind` — ENUM dropdown, **auto-populated** from chosen `mcpProvider` but **override allowed** (advanced flag)
- `executable` — computed badge (lihat indicator below)

**Visual indicators:**
- 🔴 **Red badge "Needs code"** kalau `step.executable = false` (= `code IS NULL AND (tier=ZERO OR action IS NULL)`)
- 🟢 Green check kalau executable
- 🟣 Violet `<SourcePill source="AI">` kalau di-generate AI

**Drag handle:** left side of card, 6-dot grip icon, dnd-kit `useSortable` hook. Reorder updates `step.order` field, persists via PATCH `/test-cases/:id/steps/reorder` (batch).

**Per-step actions (toolbar di top-right step card):**
- **"Translate to code"** button (AI-driven, requires LLM) — converts `action` natural language → `code` via LLM with MCP tool schema as context. `<Gated feature="ai_translation">`. POST `/agent/translate/step`. Result fills Monaco editor in-place; user reviews + saves.
- **"Test step now"** — invokes MCP tool **once** with current `code`, shows tool output (logs + return value + screenshot kalau ada) di inline drawer di bawah step. **Does not** create a Run record (ephemeral try). Endpoint: `POST /steps/test-once`. Available di semua tier.
- "Delete step" (trash icon, confirms)
- "Duplicate step"

**Mixed-MCP indicator:** kalau test case punya step dengan ≥2 distinct `mcpProvider`, header detail panel menampilkan chip `Mixed MCP: api-mcp + playwright-mcp + postgres-mcp` (mono, blue tint).

Lihat juga: [MCP_PLUGINS.md](../MCP_PLUGINS.md), [GENERATORS.md](../GENERATORS.md).

### 3.3 Test Runs

Path: `/runs` (list) and `/runs/[id]` (detail). Component: `app/(app)/runs/[[...id]]/page.tsx`.

**Top summary bar:** "Active right now" gauge (N active + bar chart of slot usage) + 5 counter blocks (Today, Passed, Failed, Avg duration, Queue).

**Layout below:** split-pane.
- Left 260px: scrollable run list. Each item: status dot + name, mono meta row (ID, branch, duration), progress bar with passed/failed/total.
- Right: run detail

**Run detail sections:**
1. Head: status badge + ID + trigger source + Cancel/Re-run/Fullscreen actions
2. Title + meta row (branch@commit, env, duration, MCP session)
3. Tabs: Logs · Steps · Artifacts · Browser · Network
4. Body: split between logs (left) and browser preview (right 280px)

**Logs panel:** monospace, near-black bg `#060606`, padded 14px. Each line: timestamp (gray) + level pill (INFO/PASS/WARN/FAIL colored) + message (white with optional `.hl` and `.dim` spans).

**Browser preview:** mock window chrome (red/amber/green dots + URL bar) + screenshot area + steps tracker (mono, current step has accent border).

**Streaming logs via WS:**
```ts
useEffect(() => {
  const socket = wsClient.subscribe(`run:${runId}`);
  socket.on('run.step.log', (line) => appendLog(line));
  socket.on('run.step.completed', updateStep);
  socket.on('run.completed', refreshSummary);
}, [runId]);
```

### 3.4 Defects

Path: `/defects`. Component: `app/(app)/defects/page.tsx`.

**Page header:** title + open count badge + "9 auto-filed by agent" badge.

**Body:** vertically stacked defect cards (gap 14px).

**Defect card:**
- Top row: severity badge + Jira link chip (mono, blue tint) + age + title + "View in Jira" + "Re-run" buttons
- Two-column body:
  - Stack trace (mono, near-black bg, red lines for `AssertionError`)
  - **Agent diagnosis** (violet tinted card, with sparkle icon + diagnosis text)
- Bottom row: linked test case, run, component, assignee

**Data:**
- `GET /api/v1/defects?status=open&sort=createdAt:desc`

### 3.5 Analytics

Path: `/analytics`. Component: `app/(app)/analytics/page.tsx`.

**Three gauges row:** Release readiness, Test coverage, Pass rate (7d). Each = small radial gauge + label + sub.

**Two-column row:** Pass rate trend (line chart) + Flaky tests list (top 5).

**Heatmap card:** 14×20 grid (14 days × 20 hours), cell color intensity per run count. Legend (Less → More) + peak hour callout.

### 3.6 Traceability

Path: `/trace`. Component: `app/(app)/trace/page.tsx`.

**Top callout:** sparkle icon + summary line ("6/6 requirements have linked test cases · 2 with open defects") + "Find gaps" button.

**3-column grid card:**
- Column 1: Requirements list. Click highlights linked items in cols 2-3.
- Column 2: Test cases — linked rows get accent-tinted bg.
- Column 3: Defects — linked rows get accent-tinted bg.

Each item shows: ID (mono), title, status badge, source/severity indicator.

### 3.7 Integrations

Path: `/integrations`. Component: `src/routes/(app)/integrations.tsx`.

**Top tabs:** All · CI/CD · Issue Tracker · Notifications · **MCP Servers** · API Discovery.

**Body (per category section):** eyebrow label + 3-col grid of integration cards.

**Integration card:**
- Logo square (32×32) + name + category + status badge (connected / off)
- Description text
- Footer: connected-since metadata + "Configure" or "Connect" button

MCP servers get green-tinted logo bg (highlight). "MCP Server" section has "Agent runtime" badge next to category label.

#### 3.7.5 Settings → LLM

Path: `/settings/llm` (sub-route di Settings layout — Settings sidebar pakai shadcn `<Tabs>` vertical atau second-level nav).

**Capability:** halaman ini **always available** di semua tier (justru ini cara user upgrade dari ZERO ke LOCAL/CLOUD).

**Form layout:**
1. **Provider dropdown** — LiteLLM supported list dengan grouping:
   - *Cloud* — Anthropic / OpenAI / Google Gemini / Groq / OpenRouter / Bedrock / Vertex / DeepSeek / xAI / Mistral / Cohere / ...
   - *Local* — Ollama / llama.cpp / vLLM / LM Studio / Text Generation Inference
   - `none` (= ZERO tier)
2. **API Key** — `<input type="password">`, write-only. Backend never returns existing key (return masked `sk-...xxxx`). Placeholder "Paste new key to update".
3. **Model** select — populated dynamically by provider (lazy load `/llm-config/models?provider=...`). For local providers, allow free-text input.
4. **Advanced (collapsible):**
   - `temperature` (slider 0-2, default 0.2)
   - `max_tokens` (number, default provider's max)
   - `base_url` override (for OpenAI-compatible local servers, custom proxies)
   - `timeout_ms` (default 60000)

**Actions:**
- **"Test connection"** button → `POST /workspaces/:id/llm-config/test` (body = form draft) → shows result: `Connected · latency: 320ms · first-token: 180ms · model echoed: claude-sonnet-4-5`. On failure, show error + suggestion ("Check API key" / "Provider unreachable").
- **"Save"** → persists encrypted (AES-GCM); triggers tier resolution server-side; flash success toast "AI features enabled" + offer modal "Upgrade autonomy from manual → assist? [Yes, recommended] [Stay manual]"
- **"Reset to ZERO"** — red destructive button at bottom (`<Button variant="destructive">`), confirm dialog "This will disable all AI features. Existing AI-generated test cases stay. Continue?" → POST `/workspaces/:id/llm-config` with `{provider: 'none'}`.

Lihat juga: [CAPABILITY_TIERS.md](../CAPABILITY_TIERS.md).

#### 3.7.6 Settings → Automation

Path: `/settings/automation`.

**Capability:** hidden di ZERO tier (autonomy locked to `manual` — no choice). In LOCAL/CLOUD: full UI.

**Radio group:** 4 autonomy levels (lihat [AUTONOMY.md](../AUTONOMY.md)):

| Level | Header | Bullet copy |
|-------|--------|-------------|
| `manual` | "Manual — human-driven" | • AI panel read-only<br>• No auto-generate, no auto-execute<br>• Use this if you want AI as a reference only |
| `assist` ⭐ | "Assist — AI proposes, human approves" (default) | • AI drafts test cases, you approve<br>• Agent asks before each tool call<br>• Diagnoses wait for review before closing |
| `semi_auto` | "Semi-auto — agent acts, human supervises P0/P1" | • P2/P3 cases auto-approve, P0/P1 gated<br>• Full agentic execution with retry policy<br>• FLAKE auto-rerun, REGRESSION blocks deploy |
| `auto` | "Auto — fully autonomous (production CI)" | • All cases auto-approve<br>• Self-heal on flake (v1.x)<br>• Auto-merge fix PRs if enabled |

Default selection per tier: ZERO → `manual` (locked); LOCAL/CLOUD first session → `assist`.

**Collapsible per-feature overrides** (advanced section, for power users):
- Generation: `auto-approve` per priority (toggle matrix P0/P1/P2/P3)
- Execution: `retry on flake` (0-5), `block on regression` (toggle)
- Diagnosis: `auto-close FLAKE` (toggle + N successful retries threshold)
- Defect filing: `auto-merge fix PR` (toggle, requires PR codegen v1.x)

**"Audit log"** link at bottom → `/settings/audit?filter=autonomy.changed`. Shows historical autonomy changes (who, when, from→to).

**Confirmation rule:** changing `assist` → `semi_auto` or higher requires **typed confirmation** ("type SEMI_AUTO to confirm"). Downgrades don't require typing.

### 3.8 Integrations expansion — MCP Servers tab

Path: `/integrations?tab=mcp` (deep-link of 3.7 tab). Component: `src/components/integrations/McpServersTab.tsx`.

**Layout:**
- Top header: "MCP Servers" eyebrow + count + "Add Custom MCP" button (primary)
- Two sub-sections:
  1. **Bundled providers** — read-only, can't delete. Includes: `api-mcp`, `playwright-mcp`, `browser-use-mcp`, `postgres-mcp`, `mongo-mcp`, `mysql-mcp`, `graphql-mcp`, `grpc-mcp`, `appium-mcp`, `kubernetes-mcp`. Show "BUNDLED" badge (gray).
  2. **Custom providers** — full CRUD. User-added MCP endpoints.

**Per-provider card:**
- Logo / icon + name + transport pill (`stdio` / `SSE` / `WS`)
- **Health status pill** — green "healthy", amber "degraded", red "down", gray "unchecked". Updates via WS `mcp.health.changed` event.
- Last health check time (relative, mono)
- "Test connection" button → `POST /mcp/providers/:id/test` → result drawer
- Tools sub-tab — toggle "Show discovered tools" — lists each MCP tool with name + description + JSON schema preview. **Dev-mode only, role-gated** (`role=admin`).
  - Each tool has "Try it" form (auto-built from JSON schema) → invokes tool dengan ephemeral context, shows return value. Useful for debugging custom MCP integrations.
- Configure button → opens edit modal (for custom; for bundled = view-only)
- "Set as default for {target_kind}" link (multiple kinds possible)

**"Add Custom MCP" modal:**
- Field 1: `name` (slug) + display name
- Field 2: `kind` — multi-select of target kinds this MCP can serve (BE_REST / FE_WEB / DATA / INFRA / CUSTOM)
- Field 3: `endpoint` URL atau executable path
- Field 4: `transport` radio — stdio / SSE / WebSocket
- Field 5: `config` JSON editor (Monaco, JSON syntax, schema-validated)
- Field 6: `secrets` — list of `key=value` (write-only, AES-GCM encrypted; passed as env vars at runtime)
- "Discover tools" preview button → connects to MCP, lists tools surfaced
- Save → POST `/mcp/providers`

**Routing config sub-section** at bottom:
- For each `target_kind` (BE_REST, FE_WEB, DATA, INFRA, CUSTOM, etc.) — drag-drop ordered list of providers (preferred → fallback)
- First provider in list = default selected in GenerateModal step 3
- Persist via PUT `/mcp/routing`

Lihat juga: [MCP_PLUGINS.md](../MCP_PLUGINS.md).

### 3.9 Run detail — diagnosis behavior

Extends section 3.3 Test Runs detail with capability-aware diagnosis card di tab "Steps" (atau dedicated section di bawah failed step).

**In CLOUD / LOCAL (with `ai_diagnosis` feature):**
- **"Agent Diagnosis"** card — violet-tinted with sparkle icon
- Content:
  - Root cause statement (1-2 sentences)
  - Confidence score (badge: `High 92%` / `Medium 68%` / `Low 41%`)
  - Evidence bullets — links to specific log lines, stack frames, network events
  - "Suggested fix" snippet (optional, if applicable)
  - "File defect" + "Mark flaky" + "Dispute diagnosis" actions
- Streaming generation kalau autonomy ≥ assist; otherwise lazy on demand (button "Diagnose with AI")

**In ZERO (no `ai_diagnosis`):**
- **"Manual triage needed"** card — gray-tinted, neutral
- Content:
  - Auto-categorized **rule-based hint** (deterministic classifier):
    - "Possible flake — assertion timed out at retry attempt 2/3" (rule: timeout assertion + flaky history)
    - "Likely regression — same step passed in run #1234 yesterday" (rule: diff vs last green run)
    - "Network error — non-2xx response, check service availability" (rule: HTTP status >= 500)
    - "Selector miss — element not found within timeout" (rule: Playwright `locator` timeout)
    - "Uncategorized — manual triage required" (fallback)
  - Auto-categorized labels: severity guess + category
  - "File defect" + "Mark flaky" + "Add note" actions
- No streaming, no LLM call, instant.

Visual difference makes tier explicit — don't hide the gray card pretending diagnosis happened.

### 3.10 Cost transparency

**v1.0 (lite):**
- **Per-run footer chip** di Run detail head: `Used 4.2k tokens · $0.034 · 3 tool calls` (`<CostChip>`). Only visible kalau `tier != ZERO` AND run includes AI calls.
- Click chip → side drawer with breakdown:
  - Per-message token count + cost
  - Per-tool-call latency + tokens
  - Total cost vs. budget remaining (if budget set)
- ZERO tier: chip hidden (no LLM cost). Show "$0 · deterministic" tiny label di footer (subtle).

**v1.x (full) — preview, not in v1.0:**
- Workspace billing page (`/settings/billing`): 7d / 30d spend per provider per kind (generation/diagnosis/translation/chat). Stacked bar chart + table.
- **Budget guard alerts** when spend approaches limit:
  - 80% → amber banner "Workspace spend at 80% of monthly budget"
  - 100% → red banner + auto-throttle (autonomy → assist forced, no auto-execute)
- Per-user spend caps (admin-set).

Lihat juga: [API.md](../API.md) untuk cost endpoints, [AI_AGENT.md](../AI_AGENT.md) untuk LiteLLM cost tracking.

### 3.11 Docs & specs

Path: `/docs`. Component: `src/routes/(app)/docs.tsx`.

**Body:** 2-column grid of source cards. Each card: icon + name + type + meta (e.g., "Notion · 142 pages · indexed 2h ago") + footer with "N test cases generated" + "Re-sync" button.

Note: in ZERO tier, "indexed" status only shows FTS index status (`fastembed` semantic indexing hidden / replaced with FTS counter). "N test cases generated" tetap relevan kalau cases di-generate via deterministic OpenAPI generator dari spec yang tersimpan di Docs.

### 3.12 Inbox

Path: `/inbox`. Component: `src/routes/(app)/inbox.tsx`.

**Body:** stacked notification cards. Each card: icon + title + body + Review/Dismiss buttons + timestamp.

Item types depend on capability:
- ZERO: deploy gate failures, flaky test promotions, manual run failures, MCP health alerts
- LOCAL/CLOUD adds: AI-generated cases pending approval (assist mode), auto-diagnosis pending review, AI fix PR pending merge

---

## 4. Shared components

### 4.1 StatusBadge
Props: `status: 'pass' | 'fail' | 'warn' | 'info' | 'ai' | 'running' | 'neutral'`, optional `label`. Renders pill with colored dot + label.

### 4.2 KpiCard
Props: `label, value, delta?, deltaDirection?, icon`. 

### 4.3 SourceDot
Tiny status dot used in tree items. Color from case `status`.

### 4.4 SourcePill  
Source label pill (MANUAL/AI/MCP/IMPORT) with appropriate tint.

### 4.5 ProgressBar
Track + fill. Variants: default (accent), warn (amber), fail (red).

### 4.6 Gauge / SmallGauge
SVG radial gauge. Pass `value` 0-100. SmallGauge variant (90×90) for analytics row.

### 4.7 ActivityRow
Used in agent activity feed + inbox. Props: `icon, tone, text, time, actions?`.

### 4.8 AgentInsightCallout
Violet-tinted card with sparkle icon. Used to surface AI annotations inline with content.

### 4.9 EmptyState
Centered icon + heading + subtitle + optional CTA. Use whenever a list is empty.

### 4.10 Gated
Capability wrapper. Props: `feature: FeatureKey`, `fallback?: ReactNode`, `children`.

```tsx
<Gated feature="ai_generation" fallback={<DisabledPlaceholder reason="LLM not configured" />}>
  {children}
</Gated>
```

Reads from `useCapabilities()` Zustand store. Re-renders on `capability.changed` WS event. Renders `null` if no fallback provided and feature disabled.

### 4.11 TierBadge
Topbar chip. Props: none (reads from `useCapabilities`). Variants per tier (gray/blue/violet — section 1.6). Click → Popover with tier info + Configure link.

### 4.12 AutonomyIndicator
Small label, e.g. "Mode: assist". Props: none (reads from `useCapabilities().autonomy`). Used in AiPanel header + optionally in Topbar. Click → opens `/settings/automation`.

### 4.13 McpProviderPill
Provider name + health dot. Props: `provider: { name, health, transport }`. Variants: healthy=green, degraded=amber, down=red, unchecked=gray. Used in step editor, Integrations cards, GenerateModal step 3.

### 4.14 DisabledTooltip
Wrapper for disabled buttons/menu items. Props: `reason: string`, `children`. Renders shadcn `<Tooltip>` on hover/focus with the reason text. Applies `aria-disabled="true"` + `pointer-events-none` to children. Use everywhere AI feature is gated off.

```tsx
<DisabledTooltip reason="LLM not configured. Settings → LLM">
  <Button disabled>Generate (AI)</Button>
</DisabledTooltip>
```

### 4.15 CostChip
Usage display. Props: `tokens: number`, `cost: number`, `currency?: 'USD'`. Renders mono "4.2k tokens · $0.034". Optional `provider?` adds prefix. Optional `toolCalls?` appends "· 3 tool calls". Click → opens breakdown drawer (run detail context).

### 4.16 DisabledPlaceholder
Fallback for `<Gated>`. Props: `reason: string`, `cta?: { label, href }`. Renders muted card with lock icon + reason + optional CTA link (e.g., "Configure LLM" → `/settings/llm`).

---

## 5. Interactions & animations

| Element | Behavior |
|---------|----------|
| Live indicator dot | `animation: pulse 2s infinite` |
| Running progress | Indeterminate stripe atau `running` color amber-ish |
| Streaming log | New line fades in (200ms opacity 0→1) + auto-scroll to bottom unless user scrolled up |
| Generated case row | `slideIn 0.3s ease-out` (translateY -4 → 0, opacity 0 → 1) |
| Modal open | shadcn default (fade + scale) |
| Hover row | bg shift to `var(--bg-elev-2)`, 120ms ease |
| Page transition | None — instant nav (this is a tool, not a brochure) |
| **Capability change** | Toast "AI features {enabled\|disabled}" + page refresh of `<Gated>` consumers (Zustand re-render) + topbar `<TierBadge>` updates |
| **MCP health change** | Topbar small **health dot indicator** (top-right, next to TierBadge) — green if all healthy, amber if any degraded, red if any down. Click → opens `/integrations?tab=mcp`. Animated transition on color change. |
| **Approval card appears** (assist mode) | Slide-in from bottom of AiPanel thread, soft chime (optional, off by default), focus-trap on action buttons |

Honor `prefers-reduced-motion` — disable pulse + slide-in.

---

## 6. Empty states (must-have)

| Screen | Empty message | CTA |
|--------|---------------|-----|
| Test Cases (no suites, ZERO tier) | "No cases yet. Generate from OpenAPI, record a browser session, or write manually." | [Generate from OpenAPI] [Record] [Write manually] (3 buttons) |
| Test Cases (no suites, LOCAL/CLOUD) | "No test cases yet. Mau generate dari PRD?" | "Generate with AI" |
| Test Cases (AI tab in ZERO) | tab hidden — not applicable |
| Test Runs | "No runs in the last 30 days. Trigger one from a test case or your CI." | "View test cases" |
| Defects | "No open defects. Suite kamu lagi clean." | "View resolved (12)" |
| Traceability (ZERO) | "No requirements imported. Paste a PRD or import OpenAPI." | "Add source" |
| Traceability (LOCAL/CLOUD) | "No requirements imported. Connect Linear, Notion, or paste a PRD." | "Add source" |
| Integrations | (never empty — always shows available options) | — |
| AI panel | (hidden entirely in ZERO — no empty state needed; shell layout reflows) | — |
| Settings → LLM (ZERO) | (form itself is the "empty" / unconfigured state) | "Test connection" once filled |

**ZERO-specific copy rule:** anywhere AI affordance would normally show, replace with link "AI features unavailable — [Configure LLM]" pointing to `/settings/llm`. Don't pretend AI exists then fail at click.

---

## 7. Aturan saat implement screen baru

0. **Wrap any AI-touching component in `<Gated>` upfront** — sebelum kasih affordance, pastikan capability gate. Otherwise screen pecah di ZERO tier.
1. **Buka mockup dulu** (`Suitest.html`) — screenshot screen yang sedang dikerjakan. **Catatan:** mockup menggambarkan CLOUD tier sebagai ideal — ZERO tier is a **subset** of what's shown. Gunakan mockup sebagai upper bound visual + adapt untuk capability gating.
2. **Match spacing** — perhatikan padding 18px page header, 24px content side, 14px card padding
3. **Match copy** — gunakan exact wording dari mockup kecuali user-content
4. **Cek typography sizes** — JANGAN naik ke 14px atau 16px kecuali ada di mockup
5. **Use design tokens** — `bg-elev-1`, `border-subtle`, dst. Jangan invent hex baru.
6. **Add empty state** — screen tanpa data harus tetap usable (lihat section 6 untuk ZERO-specific copy)
7. **Add loading state** — skeleton row untuk lists, shimmer for KPIs
8. **Wire up WebSocket / SSE** kalau data berubah real-time (runs, agent thread, capability events, MCP health)
9. **Test the screen in BOTH tiers manually before declaring done** — toggle env `SUITEST_LLM_PROVIDER=none` vs `SUITEST_LLM_PROVIDER=anthropic` dan re-verify. ZERO tier sering ke-skip, hasilnya broken UI saat user beneran di ZERO.
10. **Smoke test manually** dulu, then write Vitest unit test untuk hooks/utils, Playwright E2E untuk happy path (E2E per tier ideally)
