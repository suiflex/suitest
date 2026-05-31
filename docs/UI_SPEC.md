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

**Features keys (canonical — match `/capabilities` response in [CAPABILITY_TIERS.md § 10](../CAPABILITY_TIERS.md#10-capability-endpoint-contract)):**

- `ai_generation` — PRD / URL semantic / MCP discovery generation
- `ai_diagnosis` — root-cause narration on failed runs
- `ai_translation` — action→code at runtime + per-step "Translate to code"
- `ai_chat` — agent chat composer (text streaming, tool calls)
- `ai_panel` — whether the AiPanel surface renders at all (false in ZERO → shell reflows to 2-column grid; lihat § 2.3)
- `embeddings_semantic` — semantic search via embeddings (independent dial; can be true in ZERO if `fastembed` opt-in)
- `fts_search` — FTS fallback search (always true)
- `autonomy_assist`, `autonomy_semi_auto`, `autonomy_auto` — autonomy levels surfaced in Settings → Automation
- `auto_defect_filing_ai` — AI-reasoned auto-file (CLOUD/LOCAL only)
- `auto_defect_filing_rule` — rule-based auto-file (always true; works in ZERO)

Deterministic stuff (manual TCM, OpenAPI generator, Recorder, Crawler, MCP runner) **tidak** di-gate — selalu enabled.

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

### 3.0 Public auth routes

#### Login (`/login`)

M1e makes email/password login the primary path. The screen is a compact centered auth form using existing dark tokens:

- brand mark `suitest`
- email input
- password input
- primary "Sign in" button posting to `/auth/cookie/login`
- inline error for invalid credentials
- secondary Google OAuth button only when OAuth is configured

Public self-registration is not rendered. New users join through invitation links.

#### Accept invite (`/accept-invite?token=...`)

Public invitation route:

- validates token against `/api/v1/invitations/validate`
- shows workspace name, invited email, and role
- collects display name and password
- posts to `/api/v1/auth/accept-invite`
- redirects to `/dashboard` after the API sets the session cookie
- expired, revoked, accepted, or invalid tokens render an error state instead of a form

#### Account password

Settings -> Account contains a change-password form with current password and new password fields. If `must_change_password=true`, the app routes the user to this screen after login and blocks normal navigation until the password is changed.

#### Members invitations

Workspace Settings -> Members keeps the members table and adds an ADMIN+ "Invite" action. The invite modal collects email and role (`ADMIN`, `QA`, `VIEWER`), returns a copyable link once, and shows pending invitations with resend/revoke actions.

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

#### 3.2.0a Multi-select column (cases list)

Leftmost column of the case list table (when list view is active) and a checkbox slot prepended to tree-item rows (when tree view is active). Used by M1d-20..M1d-28 bulk-ops flows.

**Header cell:**

- Indeterminate-state checkbox = **select-all (current page only)**.
- Clicking when 0 rows checked → check all rows on the visible page.
- Clicking when some rows checked → uncheck all on page.
- Clicking when all rows on page checked → uncheck all on page.
- Tooltip on hover: "Select all on this page (N items)".

**Per-row cell:**

- Standard shadcn `<Checkbox>`. Click toggles inclusion in selection set.
- Click does **not** open detail panel (event stopped on the cell).
- `Shift+Click` selects range from last-checked row (TanStack Table `shift-click` pattern).

**Selection persistence:**

- Selection set stored in Zustand `useCaseSelection` keyed by `case.id` (Set<string>) — survives pagination boundary so users can bulk-act across pages.
- Selection cleared on filter change, tab change, or explicit "Clear selection" action.
- URL search param `?sel=ids` not used (selection is ephemeral and can exceed URL length).

**Visual:** row with `checked` state gets `bg-accent-dim` background, leaves text color unchanged.

**Tier behavior:** none — selection itself is tier-agnostic.

#### 3.2.0b Bulk-ops sticky action bar

Appears when multi-select column has ≥1 row checked. Sticky to viewport bottom of the main content area (above any global footer), `bg-elev-1 border-t border-border`, height 56px, full width of main column. Slides up 200ms on first selection, slides down on clear.

**Layout (left → right):**

- Selection count chip: `"N selected"` (mono, `text-fg-1`); shows "N of M loaded" when filtered set > selection.
- Divider.
- **Action buttons:**
  - **Delete (soft)** — destructive variant. Confirms in inline popover ("Archive N cases? They can be restored within 30 days."). On confirm → `POST /api/v1/test-cases/bulk-archive` body `{ ids: string[] }`; success → `undoToast("N cases archived", restore)`.
  - **Move to suite** — opens suite picker popover (combobox of workspace suites). On pick → `POST /api/v1/test-cases/bulk-move` body `{ ids, suiteId }`; success toast.
  - **Change priority** — opens priority popover (P0/P1/P2/P3). On pick → `POST /api/v1/test-cases/bulk-priority` body `{ ids, priority }`.
  - **Add/Remove tags** — opens dual-list popover: "Add" tag input + "Remove" tag chips picked from common tags across selection. On apply → `POST /api/v1/test-cases/bulk-tags` body `{ ids, add: [], remove: [] }`.
- Right cluster: "Clear selection" text button (`text-fg-3 hover:text-fg-1`).

**100-id cap:**

- When selection count exceeds 100, all action buttons become disabled with `<DisabledTooltip reason="Bulk actions limited to 100 items. Narrow your selection or use filters.">`.
- The count chip turns amber (`text-amber`) and shows `"100+ selected · over limit"`.
- This cap is enforced server-side too (`400 BULK_LIMIT_EXCEEDED`) — UI just prevents the round-trip.

**Tier behavior:** none — all bulk ops are deterministic and ZERO-compatible.

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

#### 3.4.1 Interactive defect card (M1d-20..M1d-28)

Defect cards become directly editable in the grid — no detail drawer required for common QA triage. All edits PATCH `/api/v1/defects/:id` (optimistic, with rollback toast on 4xx/5xx).

**Inline controls (top row of each card, replacing static badges where applicable):**

| Control | Component | Behavior |
|---------|-----------|----------|
| Status combobox | shadcn `<Select>` over enum `OPEN` / `IN_PROGRESS` / `RESOLVED` / `CLOSED` / `WONT_FIX` | Transitions follow `OPEN → IN_PROGRESS → RESOLVED → CLOSED → WONT_FIX` (forward). Backward transitions allowed for **role ≥ QA**, gated by a confirm dialog ("Reopen this defect? Move CLOSED → IN_PROGRESS"). For role=DEV/VIEWER, backward options are disabled with `<DisabledTooltip reason="QA role required to reopen">`. |
| Assignee picker | shadcn combobox over workspace users + sentinel `"Unassigned"` | Search by name/email. Avatar + name display. On change → PATCH `assigneeId`. |
| Severity edit | shadcn `<Select>` over `LOW` / `MEDIUM` / `HIGH` / `CRITICAL` | Color of badge updates immediately (`text-fg-3` / `text-amber` / `text-red` / `text-red` bold). |
| "Sync to tracker" button | secondary button with tracker logo (Jira/Linear/GitHub) | **Only enabled when an integration is connected for this workspace**. Disabled state uses `<DisabledTooltip reason="No tracker connected. Settings → Integrations">`. Label shows tracker name dynamically: "Sync to Jira", "Sync to Linear", etc. Click → POST `/api/v1/defects/:id/sync` body `{ tracker: 'jira' }`; success → toast with external link ("Filed as PROJ-1234 [Open in Jira ↗]"). |

**"Auto-filed" badge:** small violet pill `AUTO` (mono, `text-violet bg-violet/10 border-violet/20`) appears next to the title when `defect.created_by === 'system'`. Hover tooltip: "Filed automatically by {ruleEngine|agent} on {timestamp}".

#### 3.4.2 Filter chips (above grid)

Sticky row of filter chips between page header and the defect cards grid:

| Chip | Type | Multi-select | Behavior |
|------|------|--------------|----------|
| Status | multi-select chip group | yes | OPEN / IN_PROGRESS / RESOLVED / CLOSED / WONT_FIX. Default: `OPEN`. |
| Severity | multi-select chip group | yes | LOW / MEDIUM / HIGH / CRITICAL. |
| `assigneeMine` toggle | single toggle pill | n/a | "Assigned to me" on/off. Persists per-user via localStorage. |
| "Auto-filed only" toggle | single toggle pill | n/a | When on, filters `created_by=system`. |

Chips drive `GET /api/v1/defects?...` query string. Active chips use `bg-accent-dim text-fg-1 border-accent/30`. Inactive: `bg-elev-2 text-fg-3 border-border`. A "Clear filters" link sits at the right end when any chip is active.

**Tier behavior:** all defect card interactions are deterministic and ZERO-compatible. The Agent diagnosis section inside the card body still gates per § 3.9.

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

#### 3.7.1 Integration card actions (Connect / Configure / Disconnect)

Per integration card, footer button morphs by state — one workspace can hold at most one config per integration kind (lihat § 3.7.4 default-tracker toggle for multi-tracker behavior).

| State | Button | Click action |
|-------|--------|--------------|
| Not connected | "Connect" (primary, `bg-accent`) | Opens per-kind config dialog (§ 3.7.2). |
| Connected, healthy | "Configure" (secondary) + tiny ⋯ overflow → "Disconnect" | Configure → opens dialog pre-filled (masked secrets). Disconnect → confirm popover, then `DELETE /api/v1/integrations/:kind`. |
| Connected, unhealthy | "Configure" + red status dot | Hover dot → tooltip showing last error from `test-connection`. |

Status badge mirrors the green/amber/red dot pattern used elsewhere (lihat § 4.13 McpProviderPill semantics).

#### 3.7.2 Per-kind config dialogs

shadcn `<Dialog>`, max-w 560px. Field sets per integration kind:

| Kind | Fields | Notes |
|------|--------|-------|
| **Jira** | `url` (text), `email` (text), `token` (password, write-only), `auth_type` (select: `basic` / `pat` / `oauth_token`) | OAuth flow callback handled by § 3.7.5. |
| **Linear** | `pat` (password, write-only, `lin_api_...`) | |
| **GitHub** | `app_id` (text), `installation_id` (text, optional), `private_key` (file upload PEM `.pem`) | PEM stored AES-GCM encrypted server-side. |
| **Slack** | `webhook_url` (password, write-only) | URL kept secret (post-only). |
| **GitLab** | `url` (text, default `https://gitlab.com`), `project_id` (text), `webhook_secret` (password, write-only) | |

Common to all dialogs:

- All secret fields use `<input type="password">`. On open in Configure mode, fields are placeholder `"••••••••"`; user types a new value only if rotating.
- **"Test connection"** button (left of footer Cancel) → `POST /api/v1/integrations/:kind/test-connection` body = current form draft (server never persists). Returns `{ ok, latencyMs, detail }`. Shows inline result strip below button:
  - Success: green pill `Connected · 320ms · {detail}` (e.g., "user: badrus", "repo: org/proj").
  - Failure: red pill `Failed · {reason}` (mapped from server error code).
- **"Set as default tracker"** toggle (per-kind, only on tracker kinds: Jira / Linear / GitHub / GitLab) — see § 3.7.4.
- Save → `POST /api/v1/integrations/:kind` (create) or `PATCH /api/v1/integrations/:kind` (update); secrets AES-GCM at rest.

#### 3.7.3 Test connection API contract

Endpoint: `POST /api/v1/integrations/:kind/test-connection` (see API.md fix for full schema). Body mirrors save schema; response shape:

```json
{ "ok": true, "latencyMs": 320, "detail": "Authenticated as badrus@example.com" }
```

Failures use `{ "ok": false, "errorCode": "INVALID_TOKEN" | "UNREACHABLE" | "FORBIDDEN", "message": "..." }`.

UI maps `errorCode` to actionable hint ("Check API token" / "Provider unreachable, check URL" / "Token lacks required scopes").

#### 3.7.4 Default tracker toggle

Within tracker-kind dialogs (Jira / Linear / GitHub / GitLab), a "Set as default tracker for this workspace" toggle. **Only one tracker default per workspace** — flipping it on automatically flips off the previously default tracker (with toast: "Default tracker changed: Jira → Linear").

The default tracker is the destination used by:

- Auto-filed defects (rule-based or AI) — `created_by=system` defects flow there unless overridden per-suite.
- "Sync to tracker" button on defect cards (§ 3.4.1) — label updates to default tracker name.

If no tracker is set as default, "Sync to tracker" button stays disabled with `<DisabledTooltip reason="No default tracker. Settings → Integrations">`.

Persisted via `PUT /api/v1/integrations/:kind/default`.

#### 3.7.5 OAuth callback route

Path: `/integrations/oauth-callback`. Component: `src/routes/integrations/oauth-callback.tsx`. Standalone route (no app shell), full-bleed.

Handles future OAuth flows for any tracker kind. For M1d, **all flows are token-based**, so the callback is a **placeholder**:

- Reads URL query params: `?state=...&code=...&error=...&error_description=...`.
- If `error` present → renders error card: title "Connection failed", body = `error_description`, primary CTA "Back to Integrations" (→ `/integrations`).
- If `code` present → renders success card: "Connection successful. You can close this window." + auto-close attempt after 3s if opened in a popup (`window.close()`), else CTA "Back to Integrations".
- No actual token exchange happens here in M1d — placeholder copy reflects the source param verbatim for debugging.

Layout: centered card 480px wide, dark background, logo at top. No sidebar/topbar (this route is outside the app shell).

#### 3.7.6 Settings → LLM

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

#### 3.7.7 Settings → Automation

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

#### 3.7.8 Settings → Audit log

Path: `/settings/audit`. Component: `src/routes/(app)/settings/audit.tsx`. **Admin-only route** — for role < admin, render `<EmptyState>` with "Audit log requires admin role" + back link.

**Layout:**

- Page header (18px title) "Audit log" + subtitle "Workspace mutations and security-relevant events".
- Filter bar (sticky, `border-b border-border`, 14px padding):
  - `action` glob input — text, accepts `*` wildcard (e.g., `autonomy.*`, `defect.created`, `mcp.*.health`).
  - `actor` combobox — search workspace users + `system` sentinel + "Any".
  - `resource_type` select — enum (`test_case` / `suite` / `run` / `defect` / `mcp_provider` / `integration` / `workspace` / `llm_config` / `autonomy` / "Any").
  - Date range picker (shadcn `<DateRangePicker>`) — defaults to "Last 7 days".
  - "Clear" link, "Export CSV" secondary button (calls `GET /api/v1/audit-logs?...&format=csv`).
- **Virtualized table** (TanStack Virtual `useVirtualizer`, row height 44px):

| Column | Width | Content |
|--------|-------|---------|
| When | 160px | `formatDistanceToNow(ts)` + hover tooltip ISO timestamp (mono). |
| Actor | 180px | Avatar + name; for `system`, sparkle icon + "System". |
| Action | 220px | mono code-style chip (e.g. `defect.status.changed`). |
| Resource type | 120px | enum pill. |
| Resource ID | 160px | mono link → resource detail (e.g. `TC-1045` → `/cases/TC-1045`). |
| Diff | 80px | "View diff" button → opens drawer (§ below). |

**Diff drawer:** shadcn `<Sheet side="right" className="w-[640px]">`. Shows before/after JSON side-by-side (or unified). Uses a JSON diff renderer with `bg-accent-dim` for additions, `bg-red/10` for deletions. Header: who, when, action, resource link.

**Pagination:** cursor-based via `GET /api/v1/audit-logs?cursor=...&limit=100`. Infinite scroll triggered when virtualizer reaches bottom; "Load more" fallback button below table.

**No tier gating** — audit log is deterministic.

#### 3.7.9 Settings → Workspace

Path: `/settings` (root settings page). Component: `src/routes/(app)/settings/index.tsx`. Tabs at top (shadcn `<Tabs>`):

**Tab 1: General**

| Field | Editable by | Notes |
|-------|-------------|-------|
| Workspace name | OWNER, ADMIN | text input; PATCH `/api/v1/workspaces/:id` |
| Slug | nobody (display only) | mono, immutable. Tooltip: "Slug is immutable after creation." |
| Description | OWNER, ADMIN | multi-line textarea, 500 char limit |
| Default LLM provider chip | nobody (read-only) | `<TierBadge>`-style chip showing `${SUITEST_LLM_PROVIDER}` resolved by capability resolver. Hover: "Set via env. See Settings → LLM to configure workspace override." Links to § 3.7.6. |

**Tab 2: Members**

- "Invite member" button (top-right) → opens dialog: `email` input + `role` select (`OWNER` / `ADMIN` / `QA` / `DEV` / `VIEWER`). Submit → `POST /api/v1/workspaces/:id/invitations`. Success toast "Invitation sent".
- Members list table:

| Column | Content |
|--------|---------|
| User | avatar + name + email |
| Role | inline `<Select>` (OWNER, ADMIN, QA, DEV, VIEWER); PATCH `/api/v1/workspaces/:id/members/:userId` |
| Joined | relative timestamp |
| Actions | "Remove" button → confirm popover → `DELETE /api/v1/workspaces/:id/members/:userId` |

**Self-protection rules:**
- The current user **cannot remove themselves** if they are the workspace OWNER. The Remove button is disabled with `<DisabledTooltip reason="OWNER cannot remove self. Transfer ownership first.">`.
- The current user **cannot downgrade their own role** below their current role (UI hides forbidden options).

**Tab 3: Danger Zone** (OWNER-only — for non-OWNER roles, tab is hidden entirely)

- Card with destructive styling: `border-red/30 bg-red/5`.
- Title: "Delete workspace". Body: warning about cascade (test cases, runs, defects, integrations, audit logs all purged after 30-day grace period).
- **Type-slug-to-confirm input:** user must type the workspace slug exactly to enable the "Delete workspace permanently" button (`<Button variant="destructive">`).
- On click → `DELETE /api/v1/workspaces/:id` → redirect to workspace picker / new-workspace screen. Toast: "Workspace {slug} scheduled for deletion in 30 days. [Undo]" — undo button calls `POST /api/v1/workspaces/:id/restore` during grace period.

**Tier behavior:** all workspace settings are deterministic and ZERO-compatible. "Default LLM provider chip" simply shows `none` in ZERO with link to Settings → LLM (§ 3.7.6).

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

> Component-name catalog — names listed here match exactly what spec subsections (M1d-20..M1d-28 included) reference. When adding a new component, register it in this section first and import its name from screen specs rather than inventing siblings ad-hoc.

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

### 4.17 SplitGenerateButton

Primary "Generate" CTA in Test Cases header (replaces solo "Generate with AI"). shadcn `<DropdownMenu>` attached to a split-button: left half = default action, right half = chevron dropdown. Used by M1d-20..M1d-28.

**Props:**

| Prop | Type | Notes |
|------|------|-------|
| `defaultAction` | `'manual' \| 'openapi' \| 'recorder' \| 'crawler' \| 'ai'` | Defaults to `'manual'` in ZERO, `'ai'` in CLOUD/LOCAL (capability-aware). |
| `suiteId?` | `string` | Pre-fills suite picker in any modal opened. |
| `onPickGenerator?` | `(kind) => void` | Optional override; default routes to ModalRouter. |

**Menu items (top → bottom):**

| Item | Icon | Action | Enabled when | Gate |
|------|------|--------|--------------|------|
| Manual | pencil | Opens `<ManualCreateModal>` | always | none |
| Generate from OpenAPI | `{ }` | Opens `<GenerateModal>` step 2 source=`openapi`, strategy=`deterministic` locked | M2+ | `<DisabledTooltip reason="Available in M2">` until shipped |
| Record from browser | red dot | Opens Browser Recorder flow (deterministic) | M2+ | `<DisabledTooltip reason="Available in M2">` until shipped |
| Crawl URL | link icon | Opens Crawler flow (heuristic, deterministic) | M2+ | `<DisabledTooltip reason="Available in M2">` until shipped |
| Generate with AI | sparkle (violet) | Opens `<GenerateModal>` step 4 strategy=`ai_only` | CLOUD/LOCAL | `<Gated feature="ai_generation">` wrapper around item; in ZERO shows `<DisabledTooltip reason="LLM not configured. Settings → LLM">` |

**Visual:** primary button styling (`bg-accent text-accent-fg`), chevron divider uses `border-accent-fg/20`. Hover row inside dropdown: `bg-elev-2`. AI item gets a violet sparkle icon (`text-violet`) to mark capability provenance.

**Tier behavior:** the button itself **never hides** — only individual menu items are disabled. ZERO users still see "Generate" + 3 deterministic options (currently M2-pending) + 1 disabled AI option, so the affordance is discoverable.

### 4.18 ManualCreateModal

shadcn `<Dialog>`, max-w 520px. Opened from `<SplitGenerateButton>` "Manual" item and from Test Cases empty state.

**Fields:**

| Field | Type | Validation |
|-------|------|------------|
| `name` | text input | required, 1-200 chars |
| `suiteId` | suite picker combobox (search by name) | required; defaults to current suite if route has one |
| `priority` | select `P0` / `P1` / `P2` / `P3` | default `P2` |
| `tags` | tag input (`<MultiInput>` of slug chips) | optional, max 16 |
| `owner` | user picker combobox (workspace members + "Unassigned") | default = current user |

**Footer:** Cancel · "Create + Open editor" (primary, `bg-accent`).

**Behavior:**

- Submit → `POST /api/v1/test-cases` body `{ name, suiteId, priority, tags, ownerId }` → on 201, router push `/cases/:id/edit` (opens `<CaseEditor>`).
- Optimistic close + spinner on button; rollback toast on 4xx/5xx.
- `Cmd/Ctrl+Enter` submits.
- No tier gating — manual create is ZERO-compatible.

### 4.19 CaseEditor (route component)

Full-screen editor mounted at route `/cases/:id/edit`. Component: `src/routes/(app)/cases/$caseId/edit.tsx`. Not a modal — replaces main content area entirely (Sidebar + Topbar remain).

**Header (sticky, 56px, `border-b border-border`):**

- Left: editable title (inline, click-to-edit), tags pill row, priority badge (click → inline select).
- Center: save status indicator — `<SaveStatusPill>` showing `Saved · 12s ago` / `Saving…` (spinner) / `Unsaved changes` (amber dot) / `Conflict` (red dot, see below).
- Right: "Run now" button (top-right action toolbar; same placement as detail view §3.2:282), overflow menu (Duplicate, Archive, Delete).

**Tabs (shadcn `<Tabs>`):** Steps · Assertions · Requirements · Metadata.

**Steps tab:**

- `@dnd-kit/sortable` list of step cards. Drag handle = 6-dot grip (left).
- Each step row uses `<MonacoCodeEditor>` lazy-mounted for `code` field, with `<TextareaPlaceholder>` rendered until Monaco resolves.
- "Add step" button at end of list → POST `/test-cases/:id/steps` then scroll into view + focus action input.
- Reorder persists via PATCH `/test-cases/:id/steps/reorder` (batch).

**Assertions tab:** list of assertion rows (kind select, target locator, expected value).

**Requirements tab:** linked requirement IDs (combobox add, chip remove). Calls `PUT /test-cases/:id/requirements`.

**Metadata tab:** owner, suite, source (read-only pill), `created_at`, `updated_at`, audit log link.

**Save behavior:**

- **Cmd/Ctrl+S** triggers explicit save (PATCH `/test-cases/:id` with full draft). Toast on success.
- Autosave debounced 800ms on field blur (PATCH).
- **Optimistic updates with rollback:** Zustand-backed local draft; on PATCH failure, revert + `undoToast` with reason.
- **`If-Unmodified-Since` header** sent with `updated_at` of last fetched state. On `409 Conflict`, show toast: "Someone else edited this case. [View diff] [Discard mine] [Keep mine]" — diff drawer opens `/test-cases/:id/history`.
- **`useBlocker` guard** (TanStack Router) on dirty navigation: prompt "You have unsaved changes. Discard?" with Cancel / Discard.

**Tier behavior:** editor itself is ZERO-compatible. Per-step "Translate to code" button gated via `<Gated feature="ai_translation">` (existing in § 3.2.2). "AI: suggest edge cases" gated via `<Gated feature="ai_generation">`.

### 4.20 MonacoCodeEditor

Wrapper around `@monaco-editor/react`, **lazy-loaded** to keep initial bundle small (Monaco is ~3MB).

```tsx
const MonacoCodeEditor = React.lazy(() => import("@monaco-editor/react").then(m => ({ default: wrap(m.default) })));

<Suspense fallback={<TextareaPlaceholder value={code} onChange={onChange} rows={6} />}>
  <MonacoCodeEditor value={code} onChange={onChange} language={lang} />
</Suspense>
```

**Props:**

| Prop | Type | Notes |
|------|------|-------|
| `value` | `string` | Source code. |
| `onChange` | `(v: string) => void` | Debounced upstream. |
| `language` | `'typescript' \| 'python' \| 'json'` | Default `'typescript'`. From `mcpProvider.language` hint. |
| `height` | `number \| string` | Default `'auto'` (clamp 96px–480px). |
| `readOnly?` | `boolean` | For history diff view. |

**Theme:** custom Monaco theme `suitest-dark` registered on first mount — `editor.background: #111111` (`bg-elev-1`), `editor.foreground: #fafafa` (`fg-1`), `editor.lineHighlightBackground: #161616` (`bg-elev-2`), `editorLineNumber.foreground: #525252` (`fg-5`), accent `#4ade80` for selection.

**Options:** `accessibilitySupport: "on"`, `minimap.enabled: false`, `scrollBeyondLastLine: false`, `fontFamily: 'Geist Mono'`, `fontSize: 12`, `tabSize: 2`.

**No tier gating** — editor is ZERO-compatible (used for manual code authoring).

### 4.21 TextareaPlaceholder

Minimal fallback rendered inside `<Suspense>` while Monaco bundle resolves. Same `height` and typeface (`font-mono text-[11.5px]`, line-height matching Monaco's). Submits identically (same `onChange` contract).

**Props:**

| Prop | Type | Notes |
|------|------|-------|
| `value` | `string` | |
| `onChange` | `(v: string) => void` | |
| `rows?` | `number` | Default 6. |
| `placeholder?` | `string` | Default "Loading editor…". |

**Visual:** `bg-elev-1`, `border border-border`, `rounded-md`, `p-2`, no syntax highlight. A tiny "Loading editor…" eyebrow (`text-[11px] text-fg-5`) sits top-right inside the field.

### 4.22 Toaster

Sonner-based global toast surface. Mounted once in `__root.tsx` of TanStack Router tree.

```tsx
<Toaster richColors closeButton position="bottom-right" />
```

**Props (passthrough to sonner):** `richColors`, `closeButton`, `position` fixed to `bottom-right` (don't move — interactions feel anchored).

**Token usage:** sonner's theme inherits design tokens via CSS variables; override in `globals.css`:

```css
[data-sonner-toaster] {
  --normal-bg: var(--bg-elev-1);
  --normal-border: var(--border);
  --normal-text: var(--fg-1);
  --success-bg: rgba(74,222,128,.12);
  --error-bg: rgba(248,113,113,.12);
}
```

No tier gating.

### 4.23 undoToast(label, onUndo, ttlMs=8000)

Helper that fires a sonner toast with an "Undo" button. Used by soft-delete actions on **case, suite, project, requirement, defect**.

**Signature:**

```ts
undoToast(label: string, onUndo: () => Promise<void> | void, ttlMs: number = 8000): void
```

**Behavior:**

- Renders toast with body = `label` (e.g. `"Test case TC-1045 archived"`) + action button "Undo".
- Clicking "Undo" calls `onUndo()` then `toast.dismiss()`; on rejection, replace with error toast `"Undo failed: {reason}"`.
- Auto-dismisses at `ttlMs` (default 8s, matches sonner default for actionable toasts).
- After dismiss without undo, soft-delete becomes permanent (server-side: `deleted_at` flag stays; cleanup worker reaps after 30d retention — see API.md).

**Usage example:**

```ts
async function archiveCase(id: string) {
  await api.testCases.archive(id);
  undoToast(`Test case ${id} archived`, () => api.testCases.unarchive(id));
}
```

No tier gating.

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

---

## 8. M1e — Local auth, invitations & super-admin

ZERO-tier compatible (no LLM, no `<Gated>`). Authorization is purely role-based.
Shared `Role` enum: `OWNER` / `ADMIN` / `QA` / `VIEWER`.

### 8.1 `/login` — `routes/login.tsx`

- Email/password form is **primary** (posts form-encoded to `POST /auth/cookie/login`).
- "Sign in with Google" is **secondary** and rendered **only** when
  `capabilities.auth.google_oauth_enabled === true`. The route lazy-fetches
  `/capabilities` (it sits outside the `_app` guard). The button is never
  hardcoded on; an absent `auth` section ⇒ button hidden.

### 8.2 `/accept-invite` — `routes/accept-invite.tsx`

- Public. Validates `?token=` via `GET /invitations/validate`; shows
  email / workspace / role / expiry; collects name + password; expired,
  revoked, and already-accepted tokens show a clear error state.

### 8.3 Settings → Account — `routes/_app/settings.tsx` (path `/settings`)

- Tabs: **Account** (default) + **Members** (ADMIN/OWNER only).
- Account: change-password form (current + new + confirm, min 8 chars) →
  `PATCH /users/me/password`. Handles 400 wrong-current-password; on success
  refetches `["auth","me"]` so `must_change_password` clears.
- **must_change_password guard**: enforced in `routes/_app.tsx` `beforeLoad`
  (not a component effect — avoids render flash + redirect loops). When the
  flag is set and the user is not already on `/settings`, it `redirect`s to
  `/settings?force_password=1`. The page shows an amber banner
  ("You must change your password before continuing").

### 8.4 Settings → Members — `components/settings/MembersPanel.tsx`

- Members table (`GET /workspaces/:id/members`).
- **Invite** button (ADMIN+) → modal (email + role; choices ADMIN/QA/VIEWER —
  never OWNER) → `POST /workspaces/:id/invitations`. The returned one-time link
  renders with a copy-to-clipboard button (`CopyButton`).
- Pending-invites table with derived status (pending / accepted / revoked /
  expired, computed client-side from `accepted_at` / `revoked_at` /
  `expires_at`) + **Revoke** + **Resend**. Resend shows the new copyable link.
  All mutations invalidate the invitations query cache (TanStack Query).

### 8.5 Admin → Users — `routes/_app/admin.tsx` (path `/admin`)

- Visible only when `is_superuser`: the **Admin** sidebar item appears for
  superusers and the route's `beforeLoad` redirects non-superusers to
  `/dashboard`.
- Users table (workspace members — no global user-list endpoint in M1e). Per
  user **Reset password** → `POST /admin/users/:id/reset-password` → dialog
  showing the one-time `temporaryPassword` (copy button + "will not be shown
  again" warning).
- Reset-request review (`GET /admin/password-reset-requests`). On a
  `503 ENCRYPTION_NOT_CONFIGURED` response the section shows the empty state
  "Encryption not configured — reset links unavailable".

### 8.6 Shared / wiring

- `components/shared/CopyButton.tsx` — copy-to-clipboard with transient check
  state; used for invite links, reset links, and temporary passwords.
- Sidebar: **Settings** nav item + footer gear now link to `/settings`
  (previously disabled placeholders). **Admin** item shown only for superusers.
- API client (`lib/api-client.ts`): `changeOwnPassword`, `createInvitation`,
  `listInvitations`, `revokeInvitation`, `resendInvitation`, `listMembers`,
  `adminResetPassword`, `listPasswordResetRequests`, `invitationStatus`.
- OAuth-availability source: `stores/use-capabilities.ts`
  `Capabilities.auth.google_oauth_enabled`.

> Note: `Capabilities.auth` and `MeResponse.must_change_password` /
> `is_superuser` are documented contract fields not yet present in the committed
> `openapi.json`; the frontend types them as optional and degrades safely
> (OAuth button hidden, no forced password change, Admin nav hidden) until the
> backend emits them.

| 0.3 | 2026-05-31 | M1e local auth: login OAuth-conditional, accept-invite, Settings→Account/Members, Admin→Users |
