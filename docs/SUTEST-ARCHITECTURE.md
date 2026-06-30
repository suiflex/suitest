# Sutest Lifecycle — Architecture

The lifecycle lives in `packages/lifecycle` (`suitest_lifecycle`), a **stdlib-only,
ZERO-tier** package that both the `suitest test` CLI and the MCP server call. It
sits *beside* the existing Suitest stack (API / runner / TCM DB / MCP providers)
and is purely additive — nothing in the existing runner changed.

## Control flow

```
suitest.config.json
        │  load_config()                         config.py
        ▼
   ┌─────────────┐
   │ orchestrator│  run_lifecycle()              orchestrator.py
   └─────────────┘
        │
        ├─ analyze        analyzers/express.py | analyzers/react.py  → CodeSummary
        ├─ PRD            prd.py                                      → standard_prd.json
        ├─ plan           plan.py | plan_frontend.py                 → test_plan.json
        ├─ export         exporters/backend.py | exporters/frontend.py → TCxxx.py
        ├─ start          process.py (ProcessManager)                spawn target
        ├─ wait ready     readiness.py (http / port / log / timeout)
        ├─ run            runner.py (subprocess per file)            → TestResult[]
        ├─ report         report.py                                  → raw_report.md + summary.{md,json,html}
        └─ sync TCM       tcm.py                                     → tcm/cases.json + runs.json
```

## Modules

| Module | Responsibility |
|--------|----------------|
| `config.py` | Parse/validate `suitest.config.json` → typed `Config` |
| `models.py` | Dataclasses: `Endpoint`, `Page`, `CodeSummary`, `Prd`, `PlanCase`, `TestResult`, `RunSummary` |
| `paths.py` | `sutest-output/` directory layout |
| `analyzers/express.py` | Deterministic Express route discovery (mounts, router-level auth) |
| `analyzers/react.py` | React Router page discovery + `data-testid` harvest |
| `analyzers/zod_schema.py` | Reads Zod create-schemas → valid request-body synthesis |
| `prd.py` | `CodeSummary` → normalized PRD |
| `plan.py` / `plan_frontend.py` | Endpoint/page → source-traceable test cases (archetypes) |
| `exporters/backend.py` | Runnable `requests` tests (login→bearer, seeded CRUD) |
| `exporters/frontend.py` | Runnable `playwright` tests (test-id selectors, screenshot on fail) |
| `readiness.py` | `wait_until_ready` — http probe → port → ready-log → timeout |
| `process.py` | Spawn target in its own process group; drain logs; SIGTERM→SIGKILL |
| `runner.py` | Execute each `TCxxx.py` as a subprocess; map exit → outcome |
| `report.py` | `raw_report.md` + `summary.{md,json,html}` |
| `tcm.py` | TCM file mirror (source of truth) + DB-sync hook |
| `serialize.py` | TestSprite-compatible JSON shapes |
| `tools.py` | Structured `{success,summary,data,artifacts,errors}` tool wrappers |
| `mcp_server.py` | Newline-delimited JSON-RPC MCP stdio server |

## Design decisions

1. **Additive, DB + files.** TCM (Postgres) stays the source of truth; the
   lifecycle also materializes TestSprite-shaped files under `sutest-output/`.
   The file `tcm/cases.json` is a readable mirror that runs with zero infra; a
   `_try_db_sync` hook upgrades to the real `packages/db` repositories when a DB
   is reachable.
2. **Real runnable `.py`.** Generated tests are standalone (`requests` /
   `playwright`), runnable without Sutest, executed as subprocesses — matching
   TestSprite output exactly.
3. **Sutest spawns the target.** `server.startCommand` is spawned on run and
   torn down after; readiness gates execution. `autostart:false` degrades to
   readiness-only (wait for a server you started).
4. **ZERO-tier deterministic core.** No LLM is required end to end. LLM
   enrichment (via `packages/agent`) can later rewrite PRD prose / add edge cases
   *on top of* this control flow without changing it.
5. **stdlib-only.** The core drives any target with no dependency footprint;
   third-party deps live in the *target's* env (the generated tests), not here.

## Phase 2 — publish into the web app (Approach A: REST ingest)

The lifecycle still runs/records locally; an optional **publish** step pushes the
completed results into a running Suitest so the web app renders them. Flow:

```
suitest test --publish
  → lifecycle.publish.publish_results()  (lazy-imports suitest-sdk)
      → POST /api/v1/test-cases/bulk-import   (cases + steps + automation_code)
      → POST /api/v1/runs/ingest              (completed run + run_steps + VIDEO/SCREENSHOT artifacts)
  → Postgres TCM (test_cases.last_run_*, automation_code)
  → apps/web run-detail: Steps · Preview(video) · Code tabs
```

New modules: `lifecycle/{enrich,publish,frontend_runtime}.py`;
`apps/api/.../{schemas/ingest,services/ingest_service,routers/ingest}.py`;
migration `0040_tcm_automation_lastrun`. The ingest path records **already-completed**
runs — it never enqueues ARQ, and `POST /runs` is unchanged. Recording: the
frontend exporter records `.webm` video + a `<TC>.result.json` per-step sidecar;
`runner._collect_steps` folds it into `TestResult`. Enrichment: `enrich.py` adds
`llm`-tagged edge cases via a mock client (real provider through `packages/agent`
when `SUITEST_LLM_PROVIDER` is set).

## Extension points

- **New backend framework:** add `analyzers/<framework>.py` returning a
  `CodeSummary`; wire it in `orchestrator._analyze`.
- **New readiness strategy:** extend `readiness.wait_until_ready`.
- **Remote artifact storage:** publish sends `file://` artifact URLs today; add an
  S3/MinIO upload presign for fully remote web deployments.
- **Real LLM bridge:** expand `enrich._try_agent_adapter` into a LiteLLM round-trip.
