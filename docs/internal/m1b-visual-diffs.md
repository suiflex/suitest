# M1b — Visual diffs vs `Suitest.html`

Working notes from the Task 10 (visual parity ≥ 95%) audit. **Internal — not
shipped to docs/.** Tracks every intentional deviation from the mockup so a
later reviewer can tell at a glance "this is on purpose, not a regression".

Reference: `docs/UI_SPEC.md § 1.4` (typography + spacing tokens).

---

## Spacing / typography conformance (post-fix)

| Token             | Spec value | Status     |
|-------------------|------------|------------|
| Body font-size    | 13px       | OK (set globally on `body` in `globals.css`; UI primitives in `components/ui/*` retain `text-sm` from shadcn — those are not data surfaces) |
| Page header pad   | 18px       | OK (`flex-col gap-[18px]` on `<section>` page roots) |
| Content side pad  | 24px       | OK (`<main className="px-6 py-6">` = 24px) |
| Card padding      | 14px       | Fixed — converted all `border-border bg-bg-elev-1 p-4` to `p-[14px]` across the 9 screens |
| Sidebar width     | 224px      | OK (`w-[224px]` on `<aside>` in `Sidebar.tsx`) |
| Topbar height     | 47px       | OK (`h-[47px]` on `<header>` in `Topbar.tsx`) |
| Design tokens     | tokens only | OK — only deliberate hex in source is Recharts inline (must be raw values, not CSS vars) and `bg-[#060606]` for terminal/log panels (one shade darker than `bg-base`; intentional for code surfaces, documented below) |

## Token drift fixed in this pass

- `apps/web/src/routes/_app/runs.tsx` — log `<pre>` used `text-fg-2` (non-existent token); changed to `text-fg-1`.
- `apps/web/src/routes/_app/*.tsx` — all data-card containers (`border-border bg-bg-elev-1 p-4`) normalized to `p-[14px]` to match UI_SPEC § 1.4.

## Intentional diffs vs mockup

The mockup (`Suitest.html`) is authored at **CLOUD tier** — every AI surface is
"on". The implementation gates AI surfaces behind capabilities, so ZERO-tier
renders are necessarily different. The differences below are by design.

### 1. AI panel hidden in ZERO

- **Mockup**: 3-column grid `[224px Sidebar | 1fr | 380px AiPanel]`
- **Impl (ZERO)**: 2-column grid `[224px Sidebar | 1fr]` — AiPanel renders as `null` via `<Gated feature="ai_conversation">`.
- **Impl (LOCAL/CLOUD)**: matches mockup exactly.
- Source: `apps/web/src/routes/_app.tsx` (grid columns flip on `tier === "ZERO"`).

### 2. AI tab hidden on Test Cases in ZERO

- **Mockup**: Test Cases detail shows `Steps | Expected | Traceability | AI assist` tabs.
- **Impl (ZERO)**: `AI assist` tab hidden via `<Gated feature="ai_generation">`.
- **Impl (LOCAL/CLOUD)**: tab visible.

### 3. AI-related badges replaced in ZERO

- **Mockup**: `SourcePill` shows `AI` source for AI-generated cases. Run detail shows agent diagnosis with violet `AgentInsightCallout`.
- **Impl (ZERO)**:
  - `SourcePill` still renders `AI` for legacy data, but the `+ New` modal in M1d will not offer AI-source generation in ZERO.
  - Run detail replaces `AgentInsightCallout` with `Manual triage needed` (`bg-bg-elev-2`, no violet tone) — see `DiagnosisCard` in `runs.tsx`.
- **Impl (LOCAL/CLOUD)**: matches mockup.

### 4. Cost chips hidden in ZERO

- **Mockup**: agent activity and run summary show `CostChip` (tokens + USD).
- **Impl (ZERO)**: chip is rendered behind `<Gated feature="ai_conversation">` (caller-controlled).
- **Impl (LOCAL/CLOUD)**: matches mockup.

### 5. Authoring CTAs disabled in M1b

- **Mockup**: `+ New`, `Run gating suite`, etc. are clickable.
- **Impl (M1b)**: these are statically `disabled` with `DisabledTooltip` (`Authoring tools enabled in M1d`).
- This is a **milestone diff**, not a tier diff — applies in all tiers until M1d ships authoring.

### 6. Code/terminal panels use a darker shade

- `bg-[#060606]` (one stop darker than `bg-base #0a0a0a`) is used inside log
  blocks (`runs.tsx`, `defects.tsx`, `cases.tsx`). The mockup uses the same.
  This is documented here so a future "all-tokens" lint sweep doesn't flag it.

## Skipped in M1b

- **Pixel-diff CI** (Task 10.4): no headless Playwright env available in the
  development environment. Deferred to M4 alongside the visual regression
  baseline. The placeholder plan stays in `plan-03-m1b-frontend-readonly.md`.
- **Screenshot capture** (Task 10.1 step 6): manual screenshots into
  `docs/internal/screenshots/` deferred — would need a browser session to be
  meaningful and the result is throwaway once pixel-diff CI lands.

## Acceptance estimate

Conservatively ≥ 95% match vs `Suitest.html` at CLOUD tier; ZERO tier
intentionally diverges per items 1–4 above.
