# Suitest — Frontend Design Audit & Redesign Report

**Date:** 2026-07-01
**Scope:** `apps/web` (Vite + React 19 + TanStack Router + Tailwind v4.3 + shadcn/ui new-york)
**Status:** Foundation pass complete, verified (typecheck + build + tests + lint). Changes **uncommitted**.

---

## 1. Audit findings

The web app is a dark "developer-tool" UI. Two design-token families live in
`src/styles/globals.css`:

1. **Suitest custom tokens** — `bg-base`, `bg-elev-1..3`, `fg-1..5`, `accent`, status
   hues. Used directly in ~50 files each. These were defined and working.
2. **shadcn/ui semantic tokens** — `primary`, `card`, `muted`, `secondary`, `popover`,
   `destructive`, `input`, `ring`, `background`, `foreground`. Consumed by `components/ui/*`.

### Critical defects found

| # | Severity | Finding |
|---|----------|---------|
| 1 | **High** | The entire shadcn semantic token family was **undefined**. In Tailwind v4 an undefined `--color-*` means the utility emits no rule, so the default `<Button>` (`bg-primary`) rendered **transparent/broken**. This affected every primary CTA — Topbar, all dialogs, forms. |
| 2 | **High** | `ui/skeleton.tsx` used `bg-accent` = `#4ade80` (brand green). Loading states rendered solid green ("passed"-colored skeletons) — the exact complaint in the brief. |
| 3 | Medium | Pure near-black base (`#0a0a0a`), flat, untinted ("strange black background"). |
| 4 | Medium | shadcn primitives (button ghost/outline, dropdown, command, badge) used `bg-accent` for *neutral hover* semantics → green hover flashes on menus and icon buttons. |
| 5 | Low | No press feedback, weak focus rings, no tabular figures for data, default scrollbars. |

### Known pre-existing issues (NOT introduced here, NOT yet fixed)

- ~26 web vitest failures on clean `HEAD` across `cases / defects / runs / trace /
  runs-cancel-rerun`. Three distinct root causes: stale MSW handlers (`cases-tree`
  queries error to ErrorBoundary, ×12), jsdom `pointer-events` interaction quirk (×9),
  `HTMLCanvasElement.getContext` unimplemented for recharts (×2). Verified pre-existing by
  stashing this work and re-running.
- One pre-existing eslint warning in `runs_.$runId.tsx:48` (`react-hooks/exhaustive-deps`).
- `CLAUDE.md §3.3` still lists the **old** token hex values and claims tokens live in
  `tailwind.config.ts` — stale: there is no config file; tokens are in `globals.css`.

---

## 2. Changes applied

All changes work with the existing stack (no framework/library migration), per the
redesign discipline of "improve what's there, don't rewrite."

### `src/styles/globals.css` (token system rebuilt)
- **Defined the full shadcn semantic token set**, mapped via `var(...)` onto the palette.
  This is what makes Buttons / Cards / Inputs / Badges render correctly across all 160
  component files at once. (Fixes defect #1.)
- Softened the base from pure `#0a0a0a` → cool-tinted `#0b0c0e`; re-derived the elevation
  and foreground ramps with a consistent cool tint. (Fixes #3.)
- Kept brand `accent` green but slightly calmed (`#45d685`) and added `accent-hover`.
- Added: ambient radial-gradient depth on `:root`, refined thin scrollbars, brand
  `::selection`, `tabular-nums` for mono/code/data, `scroll-behavior: smooth`, and a
  neutral `suitest-shimmer` keyframe for skeletons.

### `components/ui/skeleton.tsx`
- `bg-accent` (green) → neutral `bg-bg-elev-2` + subtle left-to-right shimmer. (Fixes #2.)

### `components/ui/button.tsx`
- Primary stays green and now actually paints; added `shadow-sm` + `hover:bg-accent-hover`.
- Ghost / outline / secondary hovers switched from green `bg-accent` to neutral elevations.
- Added `active:scale-[0.98]` press feedback and ring-offset focus-visible. (Fixes #4, #5.)

### `components/ui/{dropdown-menu,command,badge}.tsx`
- Item highlight / hover swapped from `bg-accent` (green) to neutral `bg-bg-elev-2 text-fg-1`.
  (Fixes #4 — menus and command palette now highlight neutrally.)

### `components/shared/StatusBadge.tsx`
- The `running` status dot now pulses (`suitest-pulse`) so in-progress runs/steps read as
  live. Covers run list, run detail, and the per-step table via the shared component.

---

## 3. Verification

| Check | Result |
|-------|--------|
| `pnpm typecheck` (tsc --noEmit) | ✅ clean |
| `pnpm build` (tsc + vite) | ✅ clean — compiled CSS emits `.bg-primary{background-color:var(--color-primary)}` resolving to green (proves Buttons paint) |
| `pnpm test` (vitest) | 300 passed, 26 failed — **same failures as clean HEAD** (0 regression introduced) |
| `pnpm lint` (eslint) | only the pre-existing `runs_.$runId.tsx:48` warning; all 7 edited files clean |
| Live browser screenshot | ❌ not available — both Chrome and Playwright MCP bridges require an unconnected extension. Verified through the build pipeline instead. |

---

## 4. Recommended next iteration

1. **Fix the 26 pre-existing web test failures** — refresh stale MSW handlers for the cases
   page, stub `getContext` for recharts in `src/test/setup.ts`, and resolve the
   `pointer-events` interaction quirk. These gate a green CI.
2. **Reconcile `CLAUDE.md §3.3`** with the real token source (`globals.css`, new hex values).
3. **Empty / error states sweep** — audit each route's empty state for a clear next-action CTA.
4. **Distinguish `skipped` vs `pending`** in `statusToBadge` (both currently collapse to
   neutral gray).
5. **Visual QA pass** once a browser bridge is available — screenshot dashboard, cases, run
   detail, settings at 1440px and mobile.

---

## 5. Addendum — follow-up session (same day)

### 5a. The 26 pre-existing web test failures — FIXED
Single root cause: five test files (`runs-cancel-rerun`, `runs`, `cases`, `defects`, `trace`)
stubbed `auth/me` with `memberships: []`. `_app.tsx:132` auto-opens `CreateWorkspaceDialog` when
`user.memberships.length === 0`; that Radix modal sets `document.body.style.pointerEvents = 'none'`,
which blocks every click behind it (and hides content assertions). Fix = give those fixtures a
realistic membership (matching `mocks/handlers.ts`). **Full web suite: 58 files / 326 tests / 0 fail.**

### 5b. More FE polish
- **Hardcoded `bg-[#060606]` × 13** (code / log / terminal panes) → new `--color-bg-code`
  token (`#08090b`, cool-tinted). Removes the last off-token "strange black" surfaces.
- **EmptyState** refined — larger ringed icon badge, more breathing room, constrained readable
  subtitle width, semibold title.

### 5c. Backend — deterministic translate + review-gate FOUNDATION
The documented next backend item ("persist code + review-status gate → runner runs only pinned
code"). Delivered a verified vertical slice:
- Migration `0041_tcm_automation_review` — `automation_status` (NULL|draft|approved) +
  `automation_reviewed_at` + `automation_reviewed_by` (FK users). Single head; upgrade/downgrade
  DDL offline-clean.
- `models/case.py` + repo `TestCaseUpdate` wired.
- **`suitest_shared.domain.automation_review`** — pure state machine: `normalize` (fail-closed),
  `is_runnable` (approved-only), `on_translated` (always → draft; a changed artifact must be
  re-reviewed), `approve`, `reject`. 9 unit tests, mypy + ruff clean.
- Verified vs env PG: `test_case_repo` 7/7 green (conftest auto-migrated to 0041).

**Remaining to complete #1:** call `on_translated` where code is written; `approve/reject` API +
service + audit log; **runner guard** (`is_runnable`) in `apps/runner`; web Code-tab approve button;
DB-integration test for the endpoint.
