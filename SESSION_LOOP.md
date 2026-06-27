# SESSION_LOOP.md — Engineering loop for next session

> Hand-off runbook. Read this first when resuming. Encodes the TDD baseline→RED→GREEN loop
> mechanics. The **current priority** is the FE-first dogfood ZERO-readiness loop
> ([`docs/loops/ZERO_READINESS_DOGFOOD_LOOP.md`](docs/loops/ZERO_READINESS_DOGFOOD_LOOP.md));
> this file is the BE TDD sub-routine you drop into when the UI reveals a defect.

---

## 0. State at hand-off (2026-06-28)

- Branch: `main`. Working tree has the new `docs/loops/` docs (uncommitted) plus prior drift.
- **v1.0 is DONE** — `M2-12` test code export already committed (`ca9a163`). Do not redo it.
- **PRIMARY target: ZERO-tier readiness via the FE-first dogfood loop** — see [`docs/loops/ZERO_READINESS_DOGFOOD_LOOP.md`](docs/loops/ZERO_READINESS_DOGFOOD_LOOP.md). Goal: ZERO tier production-ready + publishable OSS, validated by driving Suitest's **own web UI** (FE-first, not the API) as a QA user to test https://www.saucedemo.com end-to-end from an **empty DB (keep only the user account)**. Blocker #1 already found: no create-workspace/project/suite UI in `apps/web`.
- Later phase: v2.x LLM gaps `M10`/`M11`/`M14`/`M15` (all `[ ]` in `docs/ROADMAP.md`) — do NOT start until the ZERO publish checklist (in the dogfood doc) is green.
- No baseline test output captured yet — capture one before changing code (see §2).

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
  - `SUITEST_TEST_DATABASE_URL` → `suitest_test`
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
