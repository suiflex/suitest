# Sutest Lifecycle — Usage

The `suitest_lifecycle` package adds a TestSprite-style end-to-end testing
lifecycle on top of Suitest: **analyze → generate → start → wait ready → run →
report**, driven by a single `suitest.config.json`. It runs with a stdlib-only
core (no LLM, ZERO tier) and emits TestSprite-shaped artifacts under
`sutest-output/`.

## 1. Install / run

The core has no third-party deps. From the monorepo:

```bash
# via the CLI (after `uv sync`)
suitest generate --config suitest.config.json     # analyze + generate only
suitest test     --config suitest.config.json     # full lifecycle
suitest test     --config suitest.config.json --json
suitest test     --config suitest.config.json --no-autostart   # wait for a server you started
suitest test     --config suitest.config.json --publish        # also push results into a running Suitest
suitest test     --config suitest.config.json --enrich          # add LLM edge-case cases (mock by default)

# or directly (no install), pointing PYTHONPATH at the package
export PYTHONPATH=packages/lifecycle/src
python -m suitest_lifecycle.mcp_server            # MCP stdio server
```

**Runtime:**
- Backend tests need `requests` + Python (already in the Suitest env).
- Frontend tests: **Suitest bundles the browser** — install the extra once
  (`pip install "suitest-lifecycle[frontend]"`) and Suitest auto-provisions
  Chromium on first run. The person testing their app never runs
  `playwright install` themselves — same as TestSprite. The backend the
  frontend calls is auto-started via the `dependencies` block (below).

## 2. Configure — `suitest.config.json`

Place it next to your target project (paths resolve relative to the file).

### Publish into the Suitest web app (Phase 2, optional)

Add a `publish` block to push generated cases + the completed run (with video +
per-step trace) into a running Suitest so it shows up in the web run-detail
(**Steps · Preview-video · Code** tabs). Frontend runs auto-record `.webm` video.

```json
"publish": {
  "enabled": true,
  "apiUrl": "http://localhost:4000",
  "token": "<bearer-token>",
  "workspaceId": "<workspace-id>",
  "projectId": "<project-id>",
  "suiteName": "Lifecycle — backend"
}
```

Publishing never fails a run: if the API is unreachable it logs `publish
skipped — …` and the local `sutest-output/` artifacts + file-mirror TCM still
apply. The web Code tab reads the persisted `automation_code`; the Preview tab
plays the `VIDEO` artifact.

### Backend example

```json
{
  "mode": "backend",
  "scope": "codebase",
  "projectName": "qa-test-backend",
  "projectPath": ".",
  "baseUrl": "http://localhost:4000",
  "apiBasePath": "/api",
  "readyPath": "/api/health",
  "port": 4000,
  "auth": {
    "type": "bearer",
    "loginPath": "/api/auth/login",
    "username": "admin@example.com",
    "password": "password123",
    "tokenField": "token",
    "usernameField": "email",
    "passwordField": "password"
  },
  "server": {
    "autostart": true,
    "startCommand": "npm run dev",
    "cwd": ".",
    "readyTimeoutSec": 90,
    "readyLogPattern": "running on",
    "stopGraceSec": 5
  },
  "testIds": [],
  "output": "sutest-output"
}
```

### Frontend example

```json
{
  "mode": "frontend",
  "projectName": "qa-test-frontend",
  "projectPath": ".",
  "baseUrl": "http://localhost:5173",
  "readyPath": "/",
  "port": 5173,
  "auth": { "type": "form", "username": "admin@example.com", "password": "password123" },
  "server": { "autostart": true, "startCommand": "npm run dev", "readyLogPattern": "Local:" },
  "output": "sutest-output"
}
```

### Dependencies (auto-start supporting services)

A frontend run usually needs its backend up (login → API). Declare it and Sutest
starts each dependency, waits until ready, then runs — and stops everything after:

```json
"dependencies": [
  {
    "name": "backend",
    "startCommand": "node node_modules/tsx/dist/cli.mjs watch src/server.ts",
    "cwd": "../backend",
    "baseUrl": "http://localhost:4000",
    "readyPath": "/api/health",
    "port": 4000,
    "readyTimeoutSec": 90,
    "readyLogPattern": "running on"
  }
]
```

> **Tip — broken npm bin-links:** if `npm run dev` fails with
> `ERR_MODULE_NOT_FOUND .../node_modules/dist/...`, this machine installed
> package bins as copies (not symlinks), which breaks relative imports. Invoke
> the entry file directly instead (`node node_modules/vite/bin/vite.js`,
> `node node_modules/tsx/dist/cli.mjs watch src/server.ts`).

### Key fields

| Field | Meaning |
|-------|---------|
| `mode` | `backend` or `frontend` |
| `projectPath` | target source root (relative to the config file) |
| `baseUrl` / `port` | where the target listens |
| `readyPath` | path probed for readiness (default `/api/health` BE, `/` FE) |
| `auth.*` | login flow for authenticated tests |
| `server.autostart` | `true` → Sutest spawns the target; `false` → only waits for readiness |
| `server.startCommand` | command Sutest runs to start the target |
| `server.readyTimeoutSec` | fail the run if not ready in time |
| `testIds` | subset of `TCxxx` ids to run; empty = all |

## 3. What you get — `sutest-output/`

```
sutest-output/
  <mode>/
    standard_prd.json                 PRD (features + user flows)
    suitest_<mode>_test_plan.json     test plan (cases, steps, priority, source_ref)
    TC001_*.py … TCNNN_*.py           runnable test files
    tmp/
      code_summary.json               analyzed endpoints/pages
      config.snapshot.json
      test_results.json               per-test results
      raw_report.md                   TestSprite-style report
  tcm/
    cases.json                        TCM source of truth (last_run_result, …)
    runs.json                         run history
  reports/
    summary.md  summary.json  summary.html
```

## 4. MCP lifecycle tools

`python -m suitest_lifecycle.mcp_server` exposes (each takes `config_path`,
returns `{success, summary, data, artifacts, errors}`):

`analyze_project`, `generate_test_cases`, `generate_backend_tests`,
`generate_frontend_tests`, `run_backend_tests`, `run_frontend_tests`,
`run_tests`, `sync_tcm`, `generate_report`.

## 5. Reading the report

- **Developers/QA:** `reports/summary.md` (pass rate + per-test table) or
  `summary.html`.
- **CI:** `reports/summary.json` (exit code 2 on any failure).
- **Deep dive:** `<mode>/tmp/raw_report.md` (per-test validation, coverage,
  gaps/risks) — failing tests include the captured assertion.

## 6. Known limitations

- Backend analyzer targets the modular Express/Node pattern (mounted routers).
  Other frameworks need a new analyzer (the interface is `… -> CodeSummary`).
- Frontend execution requires playwright + any backend dependency running; a
  multi-service `dependencies` block is the planned next step.
- LLM enrichment (richer PRD/edge cases) is not wired yet — the pipeline is
  fully deterministic (ZERO tier) today.
