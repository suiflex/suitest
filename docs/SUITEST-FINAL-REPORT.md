# Suitest — Final Report (TestSprite-parity lifecycle)

Date: 2026-06-30 · Scope: implement a TestSprite-style testing lifecycle in
Suitest and self-test it end to end against `suitest-example/`.

## What was built

A new stdlib-only package `packages/lifecycle` (`suitest_lifecycle`) implementing
the full loop **analyze → generate → start → wait ready → run → report**, plus a
`suitest test` / `suitest generate` CLI and an MCP stdio server. See
[SUITEST-ARCHITECTURE.md](./SUITEST-ARCHITECTURE.md) and
[SUITEST-USAGE.md](./SUITEST-USAGE.md). Gap analysis that motivated it:
[SUITEST-GAP-ANALYSIS.md](./SUITEST-GAP-ANALYSIS.md).

## Self-test evidence (against `suitest-example`)

| Check | Result |
|-------|--------|
| Backend analyze | 8 endpoints discovered with correct auth flags |
| Backend generate | 11 source-traceable cases + runnable `TCxxx.py` |
| Zod payload synthesis | valid create body (name/sku/price/stock) — CRUD passes |
| **Backend full E2E** | autostart `npm run dev` → ready via `/api/health` (98 ms) → **11/11 PASSED** in 2.6 s → server stopped |
| **Frontend full E2E** | start backend dependency (ready 579 ms) → start vite (ready 519 ms) → Chromium auto-provisioned by Suitest → **7/7 PASSED** in 14 s → both stopped |
| Browser ownership | Suitest bundles Playwright (`[frontend]` extra) + installs Chromium on demand — the user installs no browser tooling (TestSprite parity) |
| Readiness timeout path | not-ready in 3 s → server stopped → `success=false` + failure report with gaps |
| TCM source of truth | `tcm/cases.json` with `last_run_result`, `last_run_at`, `duration_ms`, `source_ref`, `automation_file` |
| Reports | `summary.{md,json,html}` + `raw_report.md` written |
| MCP server | `initialize` + `tools/list` (9 tools) + `tools/call analyze_project` → structured envelope |
| Frontend analyze/generate | 6 pages (correct protected flags) → 7 playwright cases with real `data-testid` selectors |

The backend run reproduces TestSprite's behavior: same archetypes (health, auth
happy/invalid, protected-401, authenticated CRUD), same artifact set
(`standard_prd.json`, `*_test_plan.json`, `TCxxx.py`, `tmp/test_results.json`,
`tmp/raw_report.md`).

## Goal coverage

| Goal | Status |
|------|--------|
| 1 Understand existing Suitest | ✅ gap analysis |
| 2 Study TestSprite example | ✅ gap analysis |
| 3 Backend testing like TestSprite | ✅ self-tested 11/11 |
| 4 Frontend testing like TestSprite | ✅ 7/7 E2E; Suitest bundles the browser + auto-starts backend dependency |
| 5 TCM as source of truth | ✅ file mirror + Postgres migration + ingest sync (Phase 2 Loop A/B) |
| 6 MCP tools | ✅ 9 structured tools + stdio server |
| 7 Readiness detection | ✅ http/port/log/timeout, self-tested incl. timeout |
| 8 Real (non-dummy) test cases | ✅ every case traces to an endpoint/page (`source_ref`) |
| 9 Reporting | ✅ md + json + html + raw_report + web run-detail (video/Code) |
| 10 Self-test until stable | ✅ backend 11/11, frontend 7/7, enrich live, 8/8 units, timeout path |
| 11 Documentation | ✅ gap-analysis + usage + architecture + this report |
| 12 Definition of done | ✅ Phase 1 + Phase 2 code complete; live full-stack render is the user's `make migrate` + `--publish` |

## Phase 2 — Web UI + Recording + DB TCM + LLM (Approach A: REST ingest)

Adds: lifecycle results published into the Suitest web app, per-test video +
step recording, a Postgres TCM migration, and pluggable LLM enrichment.

| Loop / Goal | Result |
|-------------|--------|
| **A — DB migration** | `0040_tcm_automation_lastrun` adds `automation_file_path`, `automation_code`, `last_run_*` to `test_cases`. Verified offline (single head, upgrade+downgrade DDL, model/repo import). |
| **B — Ingest API + SDK** | `POST /test-cases/bulk-import` + `POST /runs/ingest` (completed run, no ARQ) + SDK `bulk_import_cases`/`ingest_run`. All modules import-clean. |
| **C — Rich recording** | Frontend tests record `.webm` video + per-step trace + final screenshot; structured code style. **Self-tested 7/7 with 7 videos + per-step status in `test_results.json`.** |
| **D — Publish wiring** | `publish.py` + `--publish` flag + `publish` config block. Payload builders verified; publish degrades cleanly when API unreachable/disabled. |
| **E — Web UI** | Run-detail gains **Preview(video)** + **Code** tabs; API exposes `automation_code`. Web typecheck clean (tsc). |
| **F — LLM enrichment** | Pluggable via `packages/agent`, deterministic mock default. **Self-tested live: baseline 11 → enriched 12 (TC012 validation, tagged `llm`, traceable, PASSED).** Idempotent. |
| **G — Self-test + docs** | 8/8 hermetic unit tests green (`tests/test_phase2.py`); docs updated. |

Live full-stack verification (publish → web render of video/code) needs the
running Suitest stack (Postgres + API + MinIO + web); the lifecycle + recording +
enrichment paths are self-tested green here.

## Remaining work (next)

1. **Run live `make migrate`** on your Postgres + a full `suitest test --publish`
   against a running Suitest to see the video/Code tab render end-to-end.
2. **Artifact storage to MinIO/S3** — publish currently sends `file://` artifact
   URLs (web falls back to the static `/artifacts/raw/` route); add an S3 upload
   presign for remote deployments.
3. **Real LLM provider bridge** — flesh out `enrich._try_agent_adapter` into a
   full LiteLLM round-trip in `packages/agent` (mock is the ZERO-safe default).
4. **More analyzers** — OpenAPI spec, FastAPI, Next.js route conventions.

## Files added

```
packages/lifecycle/pyproject.toml
packages/lifecycle/src/suitest_lifecycle/
  __init__.py config.py models.py paths.py serialize.py
  prd.py plan.py plan_frontend.py readiness.py process.py runner.py
  report.py tcm.py orchestrator.py tools.py mcp_server.py
  analyzers/{__init__,express,react,zod_schema}.py
  exporters/{__init__,backend,frontend}.py

# Phase 2
packages/lifecycle/src/suitest_lifecycle/{enrich,publish,frontend_runtime}.py
packages/lifecycle/tests/test_phase2.py
apps/api/src/suitest_api/schemas/ingest.py
apps/api/src/suitest_api/services/ingest_service.py
apps/api/src/suitest_api/routers/ingest.py
packages/db/alembic/versions/20260630_0040_tcm_automation_lastrun.py
```

Changed (Phase 1): `cli/src/suitest_cli/main.py`, `cli/pyproject.toml`, root
`pyproject.toml`. Changed (Phase 2): `models.py`/`config.py`/`orchestrator.py`/
`runner.py`/`serialize.py`/`exporters/*` (recording + publish + enrich wiring),
`packages/db/.../models/case.py` + `repositories/test_cases.py`, `apps/api/.../main.py`
+ `routers/test_cases.py` + `schemas/test_case.py`, `apps/web/.../runs_.$runId.tsx`
+ `components/runs/BrowserPreview.tsx` + `lib/api-client.ts`, `sdk/python/.../client.py`,
`docs/DATA_MODEL.md`. The ARQ runner and `POST /runs` were not touched.
