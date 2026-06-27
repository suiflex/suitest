# ZERO-tier gap backlog (do this first)

> Loop backlog for the **deterministic backbone** — everything a QA engineer
> needs with **no LLM**. Embeddings (fastembed) is allowed (independent dial,
> still ZERO-safe). Read [`README.md`](./README.md) for the template + ordering,
> and [`SESSION_LOOP.md`](../../SESSION_LOOP.md) for the TDD mechanics.
>
> **Grounding:** ZERO tier is feature-complete for *authoring, deterministic
> execution, and analytics* (M0–M5 shipped). The gaps below are **operational
> and ergonomic**, not foundational — exactly the things that decide whether a
> new QA user stays past day one.

## What's already BUILT (do not redo)

| Capability | Evidence |
|-----------|----------|
| Manual TCM (cases, steps, suites, traceability) | `apps/api/src/suitest_api/routers/test_cases.py`, `routers/requirements.py` |
| Deterministic runner (MCP exec, run/steps/artifacts) | `apps/runner/src/suitest_runner/jobs/run_test_case.py` |
| Mixed-MCP test (pg → api → browser in one case) | `packages/mcp/tests/test_mixed_mcp_e2e.py` |
| Deterministic generators (OpenAPI, Recorder, URL Crawler) | `packages/agent/src/suitest_agent/generators/{openapi_generator,recorder,url_crawler}.py` |
| Semantic + lexical search | `apps/api/src/suitest_api/services/semantic_search_service.py` |
| Analytics (pass rate, coverage, flaky variance, readiness) | `apps/api/src/suitest_api/routers/analytics.py` |
| Rule-based defect auto-file | `apps/api/src/suitest_api/services/defect_auto_filer.py` |
| Test code export (Playwright/Cypress/Selenium) | `apps/api/src/suitest_api/services/code_export_service.py` |

---

## Backlog (loop order = top to bottom)

### Z1 — Root-level onboarding (`docker compose up` just works)
- **Goal (done =):** From a clean clone, a brand-new ZERO user runs **one
  documented command from repo root** and gets API + runner + Postgres + Redis +
  MinIO up, seeded, with one example test runnable. No `cd infra/docker` surprise.
- **Why (QA-user):** First touch. OSS devs abandon tools that don't start in
  five minutes. Today `docker-compose.yml` lives under `infra/docker/` while
  quickstart docs imply repo root — friction on the highest-leverage moment.
- **State:** PARTIAL — compose file at `infra/docker/docker-compose.yml`; README
  quickstart snippet exists but path mismatch.
- **Tier / gates:** ZERO. No gates.
- **Loop prompt:**
  > Make ZERO-tier onboarding frictionless from repo root. Add a root entry point
  > (root `docker-compose.yml` or a `make up` target that wraps
  > `infra/docker/docker-compose.yml`) that starts api+runner+postgres+redis+minio,
  > runs migrations, runs the Python seed, and prints the URL + a one-line
  > "run your first test" hint. Update README + `docs-site` getting-started to the
  > exact root command. Add a smoke test (or `make` target) asserting the stack
  > becomes healthy and the seeded example test can be triggered. TDD: first a
  > failing check that the root command exists and brings up a healthy API.
- **Done-check:** documented root command brings stack to healthy; `make seed`
  idempotent; getting-started doc command matches reality.

### Z2 — CI gating that actually blocks a deploy
- **Goal (done =):** A run against a project's `gating_suite` returns a
  machine-readable pass/fail that a CI step (GitHub/GitLab Actions) consumes to
  **block merge/deploy on failure**, with a non-zero CLI exit code and a status
  webhook back to the PR.
- **Why (QA-user):** "Gating = a run that blocks deploy if it fails" is a
  headline promise (glossary). The field exists but nothing enforces it. Without
  this, Suitest is a viewer, not a gate.
- **State:** PARTIAL — `gating_suite` field exists (M1d-19); no blocking logic /
  CI exit-code contract / status webhook.
- **Tier / gates:** ZERO. Audit log on the gating decision.
- **Loop prompt:**
  > Wire gating end-to-end. The CLI (`suitest run --gating --wait`) must exit
  > non-zero when the gating suite has any failed case, and emit a structured
  > result (JSON + JUnit). Add a commit-status / webhook callback so a PR check
  > flips red on failure. Audit-log the gating decision (suite, run, verdict,
  > actor). TDD: failing test that a failed gating run yields exit!=0 and a
  > `status=failed` payload; then implement.
- **Done-check:** integration test: seeded failing case in gating suite → CLI
  exit code ≠ 0 + JSON verdict `failed` + audit row written.

### Z3 — Scheduled runs (nightly regression / periodic smoke)
- **Goal (done =):** A user can schedule a suite to run on a cron expression
  (e.g. nightly regression, hourly smoke); the runner picks it up; results show
  in analytics like any run.
- **Why (QA-user):** Core daily QA rhythm. No scheduling = someone clicks "run"
  manually every night. Table stakes vs TestRail + CI cron.
- **State:** MISSING — no `cron_expression`/`scheduled_at` on the run model;
  ARQ exists for job execution but no scheduler binding.
- **Tier / gates:** ZERO. Audit log on schedule create/delete.
- **Loop prompt:**
  > Add scheduled runs. Alembic migration: a `run_schedules` table (workspace,
  > suite, cron_expression, enabled, next_run_at, last_run_at). Repository →
  > service → thin router (CRUD, ADMIN+ gate, audit log). An ARQ cron job
  > evaluates due schedules and enqueues runs. TDD: failing service test that a
  > due schedule enqueues exactly one run and advances `next_run_at`; then build.
  > Keep ZERO-safe — no LLM anywhere.
- **Done-check:** service test: due schedule → one run enqueued, `next_run_at`
  advanced; disabled schedule → no run.

### Z4 — Run retry + flaky quarantine
- **Goal (done =):** A failed run/case auto-retries with bounded exponential
  backoff; a case that flips pass/fail across retries is flagged **quarantined**
  and excluded from gating verdicts until a human clears it.
- **Why (QA-user):** Flaky handling is daily QA pain. Without retry + quarantine,
  one flaky case poisons every gating decision and erodes trust in the suite.
- **State:** MISSING — no `retry_count`/`max_retries` on the run model; flaky is
  *detected* in analytics (variance > 20%) but not *acted on*.
- **Tier / gates:** ZERO. Audit log on quarantine state change.
- **Loop prompt:**
  > Add bounded retry + quarantine. Migration: `retry_count`, `max_retries` on
  > the run/run-step model and a `quarantined` flag on the test case. Runner
  > retries failed steps with backoff up to `max_retries`. A case that flips
  > result across retries is auto-quarantined and excluded from gating (Z2)
  > verdicts; reuse the existing analytics flaky heuristic. Endpoint to
  > clear quarantine (audit-logged). TDD: failing test that a pass-then-fail
  > sequence quarantines the case and gating ignores it; then implement.
- **Done-check:** test: flip-flop result → case `quarantined=true`, gating
  verdict ignores it; manual clear → re-included, audit row written.

### Z5 — Per-case setup / teardown steps (test data lifecycle)
- **Goal (done =):** A test case can declare setup steps (run before, e.g. seed
  DB / login) and teardown steps (run after, always, even on failure) using any
  MCP provider — separate from the asserted steps.
- **Why (QA-user):** Real suites need fixtures + cleanup. Today only a
  workspace-level Python seed exists; there's no per-case data prep. Without it,
  cases leak state into each other → false flakes.
- **State:** MISSING — `run_test_case.py` runs one flat step list; no lifecycle
  phase; only `packages/db/seed.py` (workspace-level).
- **Tier / gates:** ZERO.
- **Loop prompt:**
  > Add setup/teardown lifecycle to test cases. Schema: tag steps with a
  > `phase` (setup | main | teardown) via migration. Runner executes setup →
  > main → teardown; teardown ALWAYS runs (even when main fails); only `main`
  > steps count toward pass/fail. Mixed-MCP must work across phases (seed via
  > postgres-mcp in setup, assert via playwright-mcp in main). TDD: failing test
  > that teardown runs after a main-step failure and main-only determines verdict;
  > then implement.
- **Done-check:** test: main step fails → teardown still executed; verdict
  reflects main only; mixed-MCP across phases passes.

### Z6 — Parallel step / case execution
- **Goal (done =):** Independent cases in a run (and explicitly-marked
  independent steps) execute concurrently up to a configurable cap, cutting
  wall-clock for large suites; ordering-dependent steps stay sequential.
- **Why (QA-user):** Microservice suites have hundreds of contract cases. Serial
  execution makes CI too slow to gate on. This is the difference between "runs in
  CI" and "too slow to keep."
- **State:** MISSING — `run_test_case.py` is a sequential per-step loop; ARQ gives
  cross-job concurrency but no in-run parallelism.
- **Tier / gates:** ZERO.
- **Loop prompt:**
  > Parallelize run execution. Cases within a run execute concurrently up to a
  > configurable worker cap (default from settings). Steps stay sequential within
  > a case unless explicitly marked independent. Preserve deterministic artifact
  > capture and per-case isolation. TDD: failing test that N independent cases
  > complete in ~max(case_time) not sum(case_time), with all artifacts intact;
  > then implement with bounded concurrency.
- **Done-check:** test: independent cases run concurrently under the cap;
  artifacts + verdicts identical to serial run.

### Z7 — Widen search scope to steps + assertions
- **Goal (done =):** `GET /test-cases/search` ranks over case **name +
  description + step text + assertions**, not just name+description, so "find the
  test that POSTs /checkout" actually hits step bodies.
- **Why (QA-user):** As suites grow, QA searches by *what a test does*, which
  lives in steps, not titles. Current scope misses the most useful signal.
- **State:** PARTIAL — `semantic_search_service.py` embeds only
  `name + "\n" + description`.
- **Tier / gates:** ZERO (fastembed) with lexical fallback when embeddings off.
- **Loop prompt:**
  > Expand semantic/lexical search candidate text to include step descriptions
  > and assertions, not just name+description. Keep on-demand embedding (no
  > schema change) but cap candidate text length to bound embedding cost. Lexical
  > fallback must cover the same fields. TDD: failing test that a query matching
  > only a step body returns the case; then widen the `Candidate.text` projection.
- **Done-check:** test: query present only in a step → case returned in both
  semantic and lexical modes.

### Z8 — Screenshot diff baseline (deterministic half of M11)
- **Goal (done =):** Pixel + perceptual (e.g. SSIM) diff between a run's
  screenshot artifact and a stored baseline, with a per-case threshold; over
  threshold → case fails. **No LLM.**
- **Why (QA-user):** Visual regression is a top QA need and the deterministic
  diff stands alone — the AI "why it changed" (M11-2 → `L4`) is pure enrichment
  on top. Shipping this first means visual regression works at ZERO tier.
- **State:** MISSING — ROADMAP M11-1 `[ ]`, no code. (M11-2 is the LLM half.)
- **Tier / gates:** ZERO.
- **Loop prompt:**
  > Implement deterministic visual regression (ROADMAP M11-1, M11-3). Store a
  > per-case screenshot baseline; on run, compute pixel-diff ratio + a perceptual
  > score (SSIM) vs baseline; fail when above a per-case threshold (M11-3). Diff
  > image saved as an artifact. No LLM. TDD: failing test that an above-threshold
  > change fails the case and an identical screenshot passes; then implement.
  > Leave a clean seam for the LLM explanation (L4) to consume the diff later.
- **Done-check:** test: identical image → pass; changed image above threshold →
  fail with diff artifact written.

### Z9 — Mobile + desktop MCP execution (deterministic half of M12/M13)
- **Goal (done =):** `appium-mcp` (mobile) and `computer-use-mcp` (desktop) are
  registered, routable bundled providers; a manually-authored mobile/desktop case
  executes deterministically through them. Generation (LLM) is out of scope here.
- **Why (QA-user):** Execution is tier-independent. A QA team can author mobile /
  desktop cases by hand and run them at ZERO tier long before any AI generator
  exists. Decoupling unlocks those platforms without an LLM key.
- **State:** MISSING — ROADMAP M12-1 / M13-1 `[ ]`. Bundled MCP pattern exists
  (`packages/mcp/src/suitest_mcp/bundled/`) so this follows the playwright/api
  precedent.
- **Tier / gates:** ZERO. Follow CLAUDE.md §5 bundled-MCP checklist (config +
  registry routing + `MCP_PLUGINS.md` + `DEPLOYMENT.md`).
- **Loop prompt:**
  > Add `appium-mcp` (M12-1) then `computer-use-mcp` (M13-1) as bundled providers
  > following the existing `bundled/playwright.py` + `registry.py` routing
  > pattern. Wire `target_kind` routing (FE_MOBILE, and a desktop kind). A
  > hand-authored mobile/desktop case must execute and capture artifacts through
  > the runner with no LLM. Update MCP_PLUGINS.md + DEPLOYMENT.md per the §5
  > checklist. TDD: failing routing test that a FE_MOBILE step routes to
  > appium-mcp; then implement (mock the MCP server in tests).
- **Done-check:** routing test green; mixed-MCP e2e-style test exercises the new
  provider via a mock MCP server.

---

## Suggested ordering rationale

`Z1` (first impression) → `Z2` (the gating promise) → `Z3`+`Z4` (daily rhythm +
trust) → `Z5` (real suites need fixtures) → `Z6` (keep CI fast enough to gate) →
`Z7` (search quality) → `Z8`/`Z9` (new deterministic surfaces). Ship the LLM
backlog ([`LLM_TIER_GAPS.md`](./LLM_TIER_GAPS.md)) only after the backbone holds.
