# ZERO-readiness dogfood loop (FE-first) — the driver

> **This is the primary loop** for getting ZERO tier production-ready and
> publishable. The other docs are its parts:
> [`SAMPLE_TEST_TARGETS.md`](./SAMPLE_TEST_TARGETS.md) = what to test,
> [`ZERO_TIER_GAPS.md`](./ZERO_TIER_GAPS.md) = known gaps backlog,
> [`SESSION_LOOP.md`](../../SESSION_LOOP.md) = the backend TDD mechanics you drop
> into when the UI reveals a defect.

## The principle: FE-first, BE-on-mismatch

Dogfood Suitest by **using its own frontend** to test one real web app, fully,
exactly as a ZERO-tier QA user would. Drive the **UI**, not the API.

- A journey step works in the UI → move on.
- A journey step is **missing or broken** in the UI → that is the bug. Drop to
  the backend, find root cause, fix it (TDD per `SESSION_LOOP.md`), then
  **re-verify through the UI**.
- Repeat until the **whole journey completes through the UI**, against the **real
  backend** (no mocks), with **no LLM**, against a **real target site**.

Why FE-first: the UI is the actual user contract. A green backend unit test does
not prove a ZERO user can do the thing. The UI completing the journey does.

## The one journey to drive (dogfood)

Target under test: **Swag Labs (https://www.saucedemo.com)** — full FE_WEB
journey, ZERO-friendly, public creds (see `SAMPLE_TEST_TARGETS.md` Target A).
Tool under improvement: **Suitest itself**, at ZERO tier, empty DB.

**What "empty DB" means here:** keep **only the user account** (so login works);
**zero test data** — no projects, suites, test cases, runs, or defects. A
workspace may be auto-provisioned on first login or created in step 2; nothing
else exists. This is the real fresh-install state, and it is exactly what exposes
blocker #1: with no seeded test cases, the user *must* be able to create
everything from the UI.

Drive these steps **only through the Suitest web UI**, starting from nothing:

1. Log in to Suitest.
2. **Create workspace → project → suite** from scratch.
3. Add an MCP provider (`playwright-mcp`) and **Test connection**.
4. Author a case for saucedemo (login → cart → checkout): add steps with the
   provider per step, expected results, assertions; reorder steps.
5. Search the case you just made.
6. **Run now** → watch live status/logs stream.
7. View results: steps, pass/fail, artifacts (screenshots/HAR), replay.
8. See it on the analytics dashboard (pass rate, coverage, readiness).
9. Mark the suite as a **gating suite**.
10. Make it fail (e.g. wrong assertion) → triage from artifacts → file/view a defect.
11. Confirm every LLM-only control is **hidden or shows an upgrade hint** (ZERO).

Exit when all 11 pass through the UI against a real backend and a live saucedemo.

## Current state (grounded survey, 2026-06-28)

The FE is feature-complete for **viewing, authoring, running, debugging** — but
**cannot bootstrap from empty**, which is the whole ZERO start. Blockers the loop
will hit, in journey order:

| Journey step | State | Note |
|--------------|-------|------|
| 2. Create workspace/project/suite | **MISSING** | No creation UI at all — sidebar only picks existing. **This is blocker #1.** A ZERO user with an empty DB is stuck at step 2. |
| 3. MCP "Test connection" exposure | PARTIAL | Connection-test panel exists; unclear if surfaced in the providers screen. |
| 6. Search | PARTIAL | Search input exists but no tier gating/messaging. |
| 9. Gating suite config | PARTIAL | Gating wrappers exist; no dedicated config screen found. |
| 1,4,5,7,8,10,11 | EXISTS | Login, step editor + reorder, generators modal, run + live WS, results + replay, dashboard, defects, `<Gated>` — all present. |

E2E harness reality: a Playwright suite exists at `apps/web/` **but it intercepts
`/api/v1/**` with fixtures** — it does not exercise the real backend. For this
loop, that is not enough: we need a **real-backend E2E mode** (UI → live API →
runner → DB), because the bugs we care about live in the FE↔BE seam.

## The loop procedure

Each iteration:

1. **Stand up the real stack, ZERO tier, empty DB.** Seed **only the user
   account** (login must work); no projects/suites/cases/runs/defects.
   (Onboarding gap `Z1` may bite here — fix it if so.)
   - Verify tier is ZERO: capabilities show no LLM; LLM controls hidden.
2. **Pick the lowest journey step that does not yet pass through the UI.**
3. **Try it in the real UI** (drive with Playwright against the live app, or by
   hand). Observe the actual result.
4. **If it works** → write/extend a **real-backend E2E test** that locks it in,
   then go to the next step.
5. **If it is missing/broken** → this is the defect:
   - Reproduce, then trace: is the screen missing, the API call missing, the
     contract wrong, or the backend behavior wrong?
   - Fix root cause **backend-first per `SESSION_LOOP.md`** (RED → GREEN), then
     build/adjust the FE screen, then **re-drive the UI step** to confirm.
   - If it matches a known item in `ZERO_TIER_GAPS.md`, tick it there.
6. **Re-run the whole journey** to catch regressions. Commit (conventional, no
   co-author trailer).

Stop the loop when the **exit checklist** below is fully green.

## First three iterations (concrete)

1. **Build the bootstrap UI** (blocker #1): create-workspace, create-project,
   create-suite flows in the UI, wired to the existing backend create endpoints.
   Done = a brand-new empty Suitest gets its first suite entirely via the UI.
2. **Real-backend E2E mode:** add a Playwright run config that drives the UI
   against a live api+runner+postgres (no `/api` mocks) — the harness this loop
   runs on. Done = the journey-so-far is green against the real stack in CI.
3. **MCP test-connection + first real run:** surface "Test connection" in the
   providers screen; author the saucedemo login case; "Run now"; watch it pass
   live. Done = a real run of a real site, started and observed entirely in the UI.

## Exit checklist — ZERO tier ready to publish (OSS)

**Functional (the journey):**
- [ ] All 11 journey steps complete through the UI, real backend, empty start.
- [ ] Real-backend E2E suite green in CI (not just mocked E2E).
- [ ] A real run of saucedemo passes, started + triaged entirely via the UI.
- [ ] Every LLM-only control is hidden or shows an upgrade hint at ZERO.

**Onboarding:**
- [ ] One documented root command brings the stack up, healthy, empty (`Z1`).
- [ ] getting-started doc walks the exact journey above and matches reality.

**OSS publish hygiene:**
- [ ] LICENSE present; README has quickstart + the journey screenshot/gif.
- [ ] No secrets/credentials in repo or history; `.env.example` only.
- [ ] `make ci` green (lint + typecheck FE+BE + tests + web tests).
- [ ] No dead/broken screens; no console errors on the journey screens.
- [ ] Docs banners (built vs spec) accurate for what actually ships at ZERO.

When this checklist is green, ZERO tier is production-ready and publishable. The
LLM backlog ([`LLM_TIER_GAPS.md`](./LLM_TIER_GAPS.md)) is the next phase, not a
blocker for the OSS publish.
