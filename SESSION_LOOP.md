# SESSION_LOOP.md — Engineering loop for next session

> Hand-off runbook. Read this first when resuming. Encodes the TDD baseline→RED→GREEN loop
> mechanics. The **current priority** is the FE-first dogfood ZERO-readiness loop
> ([`docs/loops/ZERO_READINESS_DOGFOOD_LOOP.md`](docs/loops/ZERO_READINESS_DOGFOOD_LOOP.md));
> this file is the BE TDD sub-routine you drop into when the UI reveals a defect.

---

## 0. State at hand-off (2026-06-28, updated)

- Branch: `main`. Working tree has prior-session drift (`docs/loops/*`, `SESSION_LOOP.md`, some `M` test files, deleted superpowers spec) **plus this session's committed work** (commits `1581db8`, `130c3b4`, `171cc31`, `dd7b449`, `be3a4a4`).
- **v1.0 is DONE** — `M2-12` test code export already committed (`ca9a163`). Do not redo it.
- **PRIMARY target: ZERO-tier readiness via the FE-first dogfood loop** — see [`docs/loops/ZERO_READINESS_DOGFOOD_LOOP.md`](docs/loops/ZERO_READINESS_DOGFOOD_LOOP.md). Goal: ZERO tier production-ready + publishable OSS, validated by driving Suitest's **own web UI** (FE-first) to test https://www.saucedemo.com end-to-end from an **empty DB (keep only the user account)**.

### Done this session (blocker #1 + real-backend e2e — all committed + verified)

- **Blocker #1 CLOSED — bootstrap UI:** `POST /workspaces` (creator→OWNER + ZERO capability; `test_workspace_create.py` 5 green) + FE create dialogs for workspace (sidebar picker `＋ New workspace` + switch), project + suite (Cases screen empty-state bootstraps + `New suite` button). FE vitest green (12 new tests), typecheck + lint green.
- **Real-backend (no-mock) e2e harness GREEN:** `make e2e-real` boots ZERO api (`make dev-api-zero`) + web, seeds one user + one empty workspace (`apps/api/scripts/seed_zero_e2e.py`), drives `apps/web/e2e/realbackend/bootstrap.spec.ts`. **Journey steps 1 (login), 2 (create project + suite), 4 (author a manual case), 5 (search), 11 (ZERO hides AI panel + AI tab) now pass through the real UI against the real backend.** Also closed: blocker #2 (manual case authoring) + blocker #3 for `test_cases` (per-workspace `public_id`, migration `0037`).

### Status: ZERO publish checklist GREEN

The 11-step journey runs through the real UI against the real backend. `make e2e-real` = **4 specs, 4 passed, 1.2m** (`bootstrap,run,defect,gating`; per-spec workspace isolation + `workers:1` + npx pre-warm). Full `make test` = **1318 passed / 0 failed**. `make check-all` green. Onboarding + README + publish hygiene done. Only `[~]` left in the exit checklist: the docs build-vs-spec banners. The v2.x LLM milestones (M10/M11/M14/M15) are the next phase.

### Earlier next-steps (now done — kept for history)

- **Run pipeline (steps 6–7) is LOCKED** in `apps/web/e2e/realbackend/run.spec.ts` (Run now → status badge streams to PASS, ~2.2m). `make e2e-real` starts the ARQ runner + seeds a runnable `e2e-run` workspace. Fixed en route: playwright-mcp cold-start timeouts, run-detail live-status refetch, and run-detail internal-id navigation.
- **Blocker #3 — per-workspace `public_id`: FULLY CLOSED** (test_cases `0037`, runs `0038`, requirements + defects `0039`). All four entities composite-unique. Apply the dev migration with: `set -a; . ./.env; set +a; uv run python -c "from alembic import command; from alembic.config import Config; c=Config('packages/db/alembic.ini'); c.set_main_option('script_location','packages/db/alembic'); c.set_main_option('sqlalchemy.url',__import__('os').environ['SUITEST_DATABASE_URL']); command.upgrade(c,'head')"` (`make migrate` is broken from repo root — relative `script_location`).
- Step 3 (DONE, UI): MCP "Test connection" already surfaced in the providers screen (Integrations → MCP → Add Custom MCP → RegisterMcpModal, ungated, vitest-covered). A *live* test needs a real `playwright-mcp` server.
- Step 5: search tier gating/messaging.
- Steps 6–7: author a saucedemo case → **Run now** → live status/logs → results/artifacts (needs the **runner** + `playwright-mcp` running — heaviest remaining piece).
- Steps 8–10: dashboard/readiness, gating-suite config screen, defect triage from artifacts.
- Publish hygiene: full `make ci` green (run the authoritative full `make test` — NOT yet run this session; the affected slice `test_workspace_create/test_workspaces/test_workspaces_settings/test_capabilities` is 42 green), LICENSE/README quickstart, no dead screens.
- Known onboarding gap surfaced: a user with **0 workspaces** can't reach the shell (`_app.beforeLoad` `/projects` 400 → `/login`). Fresh-install has the bootstrap default workspace so the dogfood is unaffected, but invited/registered-with-no-workspace users are stuck — fix before claiming full ZERO onboarding.
- Later phase: v2.x LLM gaps `M10`/`M11`/`M14`/`M15` — do NOT start until the ZERO publish checklist is green.

### Test-run discipline (learned the hard way this session)

- **NEVER run two pytest invocations at once** — `api_db` TRUNCATEs the shared remote `suitest_test` per test, so concurrent runs corrupt each other (spurious FK violations). Run serially; `pkill -f pytest` if a write test flakes with shifting FK errors.
- **Always run pytest via `make`** (loads `.env` → `SUITEST_DATABASE_URL`); bare `uv run pytest` falls back to Docker testcontainers (unavailable) → setup ERRORs.
- This machine is **darwin-arm64 but node_modules was installed for x64** — the arm64 rollup binary is missing; vitest/playwright need `@rollup/rollup-darwin-arm64` linked (env repair, kept out of commits).

### The loop docs (read these for WHAT to work on)

- [`docs/loops/ZERO_READINESS_DOGFOOD_LOOP.md`](docs/loops/ZERO_READINESS_DOGFOOD_LOOP.md) — the driver (FE-first method + 11-step journey + publish checklist).
- [`docs/loops/ZERO_TIER_GAPS.md`](docs/loops/ZERO_TIER_GAPS.md) — known ZERO gaps backlog (Z1–Z9), each with goal + loop prompt + done-check.
- [`docs/loops/SAMPLE_TEST_TARGETS.md`](docs/loops/SAMPLE_TEST_TARGETS.md) — what to test (saucedemo, restful-booker, oss.go.id).
- [`docs/loops/LLM_TIER_GAPS.md`](docs/loops/LLM_TIER_GAPS.md) — later LLM phase (L1–L6).

### Later phase — the four v2.x LLM gaps (from `docs/ROADMAP.md`) — only after the ZERO publish checklist is green

| Milestone | Scope | Acceptance items |
|-----------|-------|------------------|
| **M10** Self-healing tests | selector-change detect → AI repair → save (autonomy-gated) | M10-1..M10-4 |
| **M11** Visual regression + AI explain | pixel/perceptual diff → vision-LLM reason → per-case threshold | M11-1..M11-3 |
| **M14** Multi-agent swarm | LangGraph Planner+Executor+Critic, inter-agent bus | M14-1..M14-3 |
| **M15** PR codegen patches | REGRESSION → AI fix → open PR (auto autonomy + GitHub write + review gates) | M15-1..M15-3 |

All four are LLM-dependent → **every new endpoint needs `Depends(require_tier(Tier.CLOUD | Tier.LOCAL))`**;
side-effecting agent steps need `require_autonomy(...)`; every UI feature wraps in `<Gated>`.
Default code path must still work in ZERO tier (CLAUDE.md §4).

---

## 1. Environment — non-negotiable

This repo runs against **remote DB/Redis. NO Docker. NO localhost.**

- `.env` at repo root is fully configured (remote host `128.199.74.52`):
  - `SUITEST_DATABASE_URL` → `suitest`
  - `SUITEST_DATABASE_URL` → `suitest_test`
  - `SUITEST_REDIS_URL`, `SUITEST_LLM_*`, `SUITEST_ENCRYPTION_KEY`, `SUITEST_AUTH_SECRET`, etc.
- `make` targets auto-load `.env` (`include .env` in `Makefile`). **Prefer `make` targets** so env is always loaded.
- If running `pytest` raw, load `.env` first or vars fall back to Docker/localhost defaults → wrong DB → invalid results.

---

## 2. The loop (do these in order)

### Step 1 — Capture a VALID baseline

```bash
# Full output to file, exit code preserved. No `| tail`, no piping that masks status.
set -o pipefail
make test 2>&1 | tee /tmp/suitest_baseline.txt ; echo "EXIT=${PIPESTATUS[0]}"
```

`make test` == `uv run pytest -v` with `.env` loaded. `testpaths` (from `pyproject.toml`):
`apps/api/tests`, `apps/runner/tests`, `packages/{core,db,mcp,shared,agent}/tests`.
`asyncio_mode = strict`, `--import-mode=importlib`.

### Step 2 — Extract summary + real errors (don't read the whole file into context)

```bash
# last summary line + failures only
grep -E "passed|failed|error" /tmp/suitest_baseline.txt | tail -5
grep -nE "FAILED|ERROR|Error:|assert" /tmp/suitest_baseline.txt | head -40
```

Record: pass/fail counts, which test files fail, the actual error (not a guess).

### Step 3 — Pick ONE unit of work

**Primary path (dogfood loop):** open `docs/loops/ZERO_READINESS_DOGFOOD_LOOP.md`,
pick the lowest journey step that does not yet pass through the real UI. When it is
missing/broken, that defines the backend/frontend fix to make next.

**Backlog path:** if working a known gap, pick the next unstarted `Z#` in
`docs/loops/ZERO_TIER_GAPS.md`. One item = one PR = one commit.

### Step 4 — TDD per CLAUDE.md §8 (backend first)

1. **RED** — write failing test (Pydantic schema + service test). Run it, confirm it fails for the right reason.
2. **GREEN** — minimal code: Alembic migration (if schema) → repository → service → thin router → FE screen.
   - LLM call → via `packages/agent` (LiteLLM). Never call SDK from a route.
   - MCP call → via `packages/mcp/client`. Never invoke MCP server from a route.
   - Mock LLM first (`packages/agent/providers/mock.py`, deterministic), real provider last.
   - Tier gate + autonomy gate + audit log on every mutation.
3. **REFACTOR** — keep it green.
4. **Re-verify through the UI** (dogfood loop), then re-run `make test`, confirm GREEN, no regressions vs baseline.

### Step 5 — Verify before claiming done

- `make check-all` (lint + typecheck FE+BE) then `make test`. Both green.
- For dogfood work: the real-backend (no-mock) e2e journey step is green.
- Conventional commit, e.g. `feat(web): create-workspace flow (dogfood blocker #1)`.
- **No `Co-Authored-By` trailer** (user preference for this repo).

---

## 3. Pitfalls that broke an earlier session — do NOT repeat

1. **`.env` not loaded** → tests fell back to Docker/localhost → wrong DB.
   Fix: use `make` targets (auto-load `.env`); never assume Docker.
2. **`| tail` masked pytest exit code + truncated output** → baseline looked done but was invalid.
   Fix: `tee` to a file, read `PIPESTATUS`/`set -o pipefail`, summarize from the file (§2 step 2).
3. **Reading full pytest output into the conversation** burns context.
   Fix: write to `/tmp/suitest_baseline.txt`, grep summary + failures only.
4. **Mocked e2e ≠ proof.** The Playwright suite at `apps/web/` intercepts `/api/**`.
   For the dogfood loop, drive the UI against the REAL backend, not fixtures.

---

## 4. Quick command reference

```bash
make test                 # all Python tests, .env loaded
make test-file f=path     # single file
make test-cov             # with coverage
make check-all            # lint + typecheck (FE+BE), no tests
make ci                   # check-all + test + test-web (full CI locally)
make migrate              # Alembic upgrade head (.env loaded)
make seed                 # Python seed script (never persistent demo data)
```

> Stack startup for the dogfood loop (api + runner + web, ZERO tier, empty DB except
> the user account) is not yet a one-command target — that is onboarding gap `Z1`.
> Discover the run commands from the `Makefile` / `apps/web/package.json` and, if
> missing, fixing `Z1` is the natural first dogfood iteration.

---

## 5. Resume checklist

- [ ] Read this file + `docs/loops/ZERO_READINESS_DOGFOOD_LOOP.md`.
- [ ] Run §2 Step 1 → valid baseline in `/tmp/suitest_baseline.txt`.
- [ ] Run §2 Step 2 → record real summary + errors.
- [ ] Stand up the real stack at ZERO tier, empty DB (user account only).
- [ ] Drive the dogfood journey through the UI; pick the first failing step.
- [ ] TDD RED → GREEN → re-verify via UI → conventional commit (no co-author trailer).
