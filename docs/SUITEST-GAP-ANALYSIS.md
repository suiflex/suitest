# SUITEST — Gap Analysis vs TestSprite

> **Goal 1 + 2 deliverable.** Compares the current `suitest` codebase against the
> `testsprite-example/` gold-standard output, and defines the gap that the Suitest
> Engineering Loop (Goals 3–12) must close.
>
> Date: 2026-06-30 · Status: analysis (no code changed yet)

---

## 1. What Suitest is today

Suitest is a **web-driven, DB-centric test-management product** (FastAPI API + React web +
ARQ runner + MCP provider layer + Postgres TCM). It is **not** a CLI lifecycle tool — runs are
triggered from the UI/REST, dispatched per-step through MCP, and results live in Postgres.

| Subsystem | State | Location |
|-----------|-------|----------|
| TCM data model | ✅ rich (cases/steps/suites/runs/run-steps/defects/artifacts/tags) | `packages/db/src/suitest_db/models/` |
| Deterministic runner | ✅ ARQ worker, per-step MCP dispatch | `apps/runner/src/suitest_runner/` |
| MCP providers | ✅ 9 bundled (playwright, api_http, postgres, graphql, grpc, mysql, mongo, k8s, in-process) | `packages/mcp/src/suitest_mcp/bundled/` |
| Generators | ✅ 10 (openapi, url_crawler, url_semantic, prd, mcp_discovery, classifier, recorder, diff_selector, openapi_enrich, _drafts) | `packages/agent/src/suitest_agent/generators/` |
| Generation graph | ✅ classify → draft → parse | `packages/agent/src/suitest_agent/graphs/generation.py` |
| Defects (rule-based) | ✅ auto-file on step FAIL | `apps/runner/src/suitest_runner/handlers/step_handler.py` |
| Artifacts (S3/MinIO) | ✅ screenshots/logs/video | `apps/runner/src/suitest_runner/artifacts.py` |
| CLI | ⚠️ thin REST wrapper only (`run`, `cases list`, `mcp ls`) | `cli/src/suitest_cli/main.py` |
| Readiness detection | ❌ **NOT FOUND** | — |
| Target server startup | ❌ **NOT FOUND** (assumes target already up) | — |
| File-based report | ❌ only DB + external-sync stubs (XRay/qTest) | `apps/api/.../reporter_service.py` |
| Runnable test-file export | ❌ steps stay as MCP-JSON envelopes in DB | — |

### TCM model field coverage (vs TestSprite needs)

`TestCase` (`models/case.py`) already has strong traceability:
`source: CaseSource` (RECORDER/OPENAPI/PRD/URL_CRAWLER/SEMANTIC/MCP…), `status`, `priority`
(P1–P3), `generated_by`, `generated_from: dict` (JSON source ref), `preconditions`, `estimated_ms`.
`TestStep` has `action`, `expected`, `code`, `data`, `mcp_provider`, `target_kind`.
`Run` has `status`, `duration_ms`, `passed_steps`/`failed_steps`/`total_steps`, `tier_at_runtime`.
`RunStep` has `outcome`, `duration_ms`, `stdout`/`stderr`, `error_message`, `error_stack`,
`state_snapshot`.

**Missing fields** to add for full parity:
- `TestCase.automation_file_path` (link case → exported `TCxxx.py`)
- `TestCase.last_run_id` / `last_run_result` / `last_run_at` (denormalized for fast report/UI)
- `Run.run_configuration` (mode/scope/auth/port snapshot — can reuse `metadata_json` initially)

---

## 2. What TestSprite produces (the target behavior)

TestSprite is a **CLI/MCP lifecycle** that writes a self-contained `testsprite_tests/` folder.
Per mode (backend **or** frontend) it emits ~40 files:

| Artifact | Role |
|----------|------|
| `tmp/config.json` | front-door config: `type` (backend/frontend), `localEndpoint`, `port`, `serverMode` (development/production), auth creds, `testIds`, `additionalInstruction` |
| `tmp/code_summary.yaml` | code analysis: tech stack, features, **all endpoints with request/response schemas** (backend) or routes/flows (frontend) |
| `standard_prd.json` | normalized PRD: `meta`, `product_overview`, `core_goals`, `features[]` (name/description/user_flows), `code_summary` |
| `testsprite_{mode}_test_plan.json` | test plan. **Backend:** `[{id,title,description}]`. **Frontend:** `[{id,title,description,category,steps[],priority}]` (steps typed `action`/`assertion`, creds templated as `{{LOGIN_USER}}`) |
| `TCxxx_*.py` | **standalone runnable test files** (see below) |
| `tmp/test_results.json` | `[{projectId,testId,title,description,code,testStatus(PASSED/FAILED),testError,testType,createFrom,created,modified}]` |
| `tmp/raw_report.md` | human report: ① metadata + summary ② per-requirement validation ③ coverage table ④ gaps/risks |

### Generated test-file shape

**Backend** (`TC007_post_api_products...py`): plain `import requests`, base URL
`http://localhost:4000/api`, login → extract JWT → `Authorization: Bearer …` → assert
status + JSON body. Each file is **directly runnable** and ends by calling its own test fn.

**Frontend** (`TC013_Delete_product...py`): `playwright.async_api`, headless Chromium against
`http://localhost:5173`, locates elements via `get_by_test_id` / `get_by_role` / xpath, performs
real login, asserts with `expect(...).to_contain_text(..., timeout=15000)`, scrolls into view.

### Inferred lifecycle (the loop Suitest must match)

```
config (mode/scope/auth/port/PRD)
  → analyze source code        → tmp/code_summary.yaml
  → generate PRD               → standard_prd.json
  → generate test plan         → testsprite_{mode}_test_plan.json
  → generate test code         → TCxxx_*.py
  → START server / wait READY  → (health / DOM load / tunnel)
  → execute selected tests     → tmp/test_results.json
  → generate report            → tmp/raw_report.md
```

---

## 3. The Gap (what Suitest must build)

| # | Capability | TestSprite | Suitest now | Action (Goal) |
|---|-----------|:---------:|:----------:|---------------|
| G1 | **Lifecycle orchestrator** (analyze→generate→start→wait→run→report) as one command | ✅ | ❌ (UI/REST only) | New `suitest test` CLI + orchestrator service (Goals 3,4) |
| G2 | **Config front-door** (mode/scope/auth/port/path/PRD) | ✅ `config.json` | ❌ | `suitest.config.json` schema + loader (Goal 4) |
| G3 | **Code analysis → code_summary** (endpoints+schemas / routes) | ✅ | partial (openapi/url generators exist, no unified summary) | Reuse generators → emit `code_summary` (Goal 8) |
| G4 | **PRD normalization** to `standard_prd.json` | ✅ | `prd.py` consumes PRD, doesn't emit standard PRD | Add PRD emitter (Goal 8) |
| G5 | **Test plan** JSON (backend slim / frontend rich+steps) | ✅ | drafts in-memory only | Persist plan artifact + TCM (Goals 5,8) |
| G6 | **Runnable test-file export** (`TCxxx.py`) | ✅ | ❌ steps stay MCP-JSON in DB | Code-export layer: TCM step → pytest/requests + playwright file (Goals 3,4) |
| G7 | **Server startup** of target under test | ✅ | ❌ assumes running | Process manager: spawn backend/frontend from config (Goal 7) |
| G8 | **Readiness detection** before execute | ✅ health/DOM/tunnel | ❌ | Readiness checker: health endpoint / port / ready-log / page-load / timeout-fallback (Goal 7) |
| G9 | **File report** `raw_report.md` + `test_results.json` (+ html) | ✅ | DB + external stubs only | Reporter writing `suitest-output/reports/summary.{md,json,html}` (Goal 9) |
| G10 | **TCM as source of truth synced to runs** | partial (files) | ✅ DB strong, but no last-run denorm / file link | Add `automation_file_path`, `last_run_*`; sync after run (Goal 5) |
| G11 | **Structured MCP tools** (analyze/generate/run/report) | ✅ | MCP = providers, not lifecycle tools | Expose lifecycle as MCP tools w/ `{success,summary,data,artifacts,errors}` (Goal 6) |

### Strategic note — DB-centric vs file-centric

Suitest's strength is its **Postgres TCM** (richer than TestSprite's flat JSON). The gap is **not**
"replace the DB with files" — it is to add a **file-emitting lifecycle layer on top of the existing
TCM** so that:

- TCM stays the **source of truth** (Goal 5),
- but every run also materializes TestSprite-shaped artifacts under `suitest-output/` (PRD, plan,
  runnable `TCxxx.py`, `test_results.json`, `raw_report.md`),
- and the orchestrator adds the two missing runtime pieces TestSprite has and Suitest lacks:
  **server startup** + **readiness detection**.

This keeps existing runner/MCP/generators intact and additive.

---

## 4. Build order (maps to Engineering Loop)

1. **Loop 4** — Config schema (`suitest.config.json`) + `suitest-output/` layout + TCM migration
   (`automation_file_path`, `last_run_*`).
2. **Loop 5 (backend)** — orchestrator: analyze (openapi/code) → code_summary → standard_prd →
   test_plan → export `TCxxx.py` (requests) → **start backend + wait ready** → execute → results →
   sync TCM → report.
3. **Loop 6 (frontend)** — same lifecycle with playwright export + **start frontend + wait DOM
   ready**; capture screenshot/video on fail.
4. **Loop 7** — TCM sync layer (run → update case `last_run_*`, link automation file).
5. **Loop 8** — MCP lifecycle tools (`analyze_project`, `generate_test_cases`,
   `generate_backend_tests`, `generate_frontend_tests`, `run_backend_tests`, `run_frontend_tests`,
   `sync_tcm`, `generate_report`) with structured output.
6. **Loop 9** — reporting (`summary.md` / `.json` / `.html`).
7. **Loop 10** — self-test against `suitest-example/` (the bundled target app) end-to-end.
8. **Loop 11–12** — docs + final report.

---

## 5. Open architecture decisions (need confirmation before Loop 4)

1. **Artifact strategy** — emit TestSprite-shaped files under `suitest-output/` *in addition to*
   the DB TCM (recommended), vs DB-only, vs files-only.
2. **Generated-test runtime** — export real runnable `TCxxx.py` (`requests` + `playwright`,
   TestSprite-identical, runnable without Suitest) vs keep MCP-JSON steps and only render files for
   reading.
3. **Server startup ownership** — Suitest spawns the target (needs a `start` command per mode in
   config) vs Suitest only waits for a user-started server (readiness only, no startup).
4. **Lifecycle entrypoint** — new `suitest test` CLI subcommand driving the orchestrator
   (recommended) vs MCP-tools-only vs REST endpoint.
