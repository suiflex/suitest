---
title: MCP tool reference
description: All 22 tools exposed by the Suitest MCP server, with arguments, return envelopes, and grouping into lifecycle and blackbox tools.
---

The Suitest MCP server (`npx -y @suiflex/suitest-mcp`, or `python -m suitest_lifecycle.mcp_server`) is a stdio server speaking newline-delimited JSON-RPC 2.0 (MCP protocol version `2024-11-05`). It exposes **22 tools** in two groups:

- **Lifecycle tools** (10): config-driven testing of a project you have a checkout of. Every tool takes a `config_path` pointing at a [`suitest.config.json`](/docs/reference/configuration/).
- **Blackbox tools** (12, including `bootstrap_project`): no-repo testing of a running web app from a URL and test credentials. They take structured keyword arguments instead of just a config path.

Install and IDE wiring: [Install the MCP server](/docs/install/mcp-server/). Typical agent flows: [Agent workflow](/docs/guides/agent-workflow/) and [Blackbox testing](/docs/guides/blackbox-testing/).

## The result envelope

Every tool returns the same structured envelope, serialized as JSON text content:

```json
{
  "success": true,
  "summary": "human-readable one-liner",
  "data": {},
  "artifacts": ["paths to files produced"],
  "errors": []
}
```

Expected failures (bad config, target not ready, missing prior stage) never raise; they come back as `success: false` with `errors` filled in. The MCP response also sets `isError` when `success` is false.

## Server startup credential gate

At startup the server checks `SUITEST_API_URL` and `SUITEST_API_KEY`. Both must be set and the key must authenticate against `GET /api/v1/api-keys/whoami` on that URL, otherwise the server refuses to start. The key pins the workspace and project that every tool publishes into. See [Environment variables](/docs/reference/environment/).

## Lifecycle tools

### Input schema

All ten lifecycle tools share this schema. `config_path` is required (default `"suitest.config.json"`):

```json
{
  "type": "object",
  "properties": {
    "config_path": {
      "type": "string",
      "description": "Path to suitest.config.json",
      "default": "suitest.config.json"
    }
  },
  "required": ["config_path"]
}
```

The three run tools (`run_tests`, `run_backend_tests`, `run_frontend_tests`) additionally accept:

| Argument | Type | Default | Description (from code) |
|---|---|---|---|
| `recreate_project` | boolean | `false` | "EXPLICIT opt-in: recreate the project when the configured publish.projectId no longer exists and repair finds no match. Without this flag a stale binding FAILS the run (nothing is inserted)." |

### analyze_project

> Static-analyze the target project; list endpoints (backend) or pages (frontend).

Runs the Express analyzer (backend mode) or the React analyzer (frontend mode) over `projectPath` without generating anything. Returns the code summary in `data` (endpoints or pages) and a summary like `analyzed backend: 12 endpoints`.

### generate_test_cases

> Analyze, build a PRD + test plan, and export runnable test files.

Full generation without execution. Returns the generated cases in `data.cases` plus a change report when one exists, and lists artifacts: `prd.json`, `test_plan.json`, `code_summary.json`, and every exported test file.

### generate_backend_tests

> Generate backend (requests) test files. Errors if config mode != backend.

Mode-guarded wrapper around `generate_test_cases`: fails with `success: false` and a `mode mismatch` error when the config declares a different mode.

### generate_frontend_tests

> Generate frontend (playwright) test files. Errors if config mode != frontend.

Same mode guard for frontend configs.

### run_backend_tests

> Full backend lifecycle: start, wait ready, run, report. Mode-guarded.

Runs the complete lifecycle (analyze, generate, start the target, readiness probe, execute, report, optionally publish). Accepts `recreate_project`. Returns the run summary in `data` (totals, per-case results, and a `retest` block when a retest was performed), plus report artifacts.

### run_frontend_tests

> Full frontend lifecycle: start, wait ready, run, report. Mode-guarded.

Frontend counterpart of `run_backend_tests`, same arguments and return shape.

### run_tests

> Run the full lifecycle for whatever mode the config declares.

Mode-agnostic full run. Accepts `recreate_project`. Same return shape as the mode-guarded run tools.

### sync_tcm

> Report the TCM mirror (case/run counts + file paths).

Reads the local TCM mirror files. Returns `data.cases` and `data.runs` counts and the paths of `tcm_cases.json` and `tcm_runs.json` as artifacts.

### generate_report

> Re-surface the last run's report artifacts without re-running.

Fails with `no prior run found` when `reports/summary.json` is missing. Otherwise returns the report paths as artifacts: `summary.md`, `summary.json`, `summary.html`, and the raw report markdown.

### get_failure_context

> Call this WHENEVER a run reports failing test(s) and you intend to fix the code. Returns a compact markdown bundle for the last run's failures (error + failed step + DOM excerpt around the failed selector + error/warning console + non-2xx network + evidence links), sized to fit an agent context window (<= 8 KB) so you can diagnose and fix WITHOUT opening screenshots/videos by hand. No prior run -> error; run with no failures -> empty context.

Reads the stored `reports/summary.json`; never re-runs. Returns `data.failure_context` (the markdown bundle) and `data.failed_cases`. With no prior run it fails; with a prior all-green run it succeeds with an empty context. See [Failure context guide](/docs/guides/failure-context/).

## Blackbox tools

The blackbox engine tests any web app from a URL, with no repo access. Tools chain through JSON state files saved under the output directory (`suitest-output/` by default), so every stage can also be called independently in a fresh session: discover, graph, generate, run, summarize.

### Input schema

All blackbox tools (and `bootstrap_project`) share one schema. Every property is optional; each tool reads the ones it needs:

| Argument | Type | Description (from code) |
|---|---|---|
| `config_path` | string | Optional suitest.config.json with a 'ui' blackbox section |
| `url` | string | Target app URL (overrides config) |
| `username` | string | Test credential username/email |
| `password` | string | Test credential password |
| `max_routes` | integer | Crawl route cap |
| `page_url` | string | Route or absolute URL (blackbox_analyze_page only) |
| `project_path` | string | Project directory for the setup wizard (bootstrap_project) |
| `timeout_sec` | integer | How long to wait for the user to submit the wizard (bootstrap_project) |
| `project_id` | string | Suitest project id to publish into (blackbox_publish_results) |
| `recreate_project` | boolean | EXPLICIT opt-in: recreate the project when the configured/passed project id no longer exists and repair finds no match (blackbox_publish_results). Without it a stale binding fails the publish. |
| `prd_file` | string | Markdown PRD path, for a PRD-driven semantic plan via the workspace LLM (blackbox_generate_playwright_tests) |

Config resolution per call: an explicit `config_path` (with a `ui` section) wins; bare `url` / `username` / `password` arguments are enough for the no-config quick path. If neither a target URL nor a config is given, the tool fails with `no target: pass url=... or a config_path with ui.targetUrl/baseUrl`.

### bootstrap_project

> Open a browser setup wizard (target URL, credentials, crawl scope, optional markdown PRD upload); writes suitest.config.json into the project and returns its path. Call this FIRST when no config exists.

Arguments: `project_path` (default `"."`), `timeout_sec` (default `600`). Blocks until the user submits the form or the timeout elapses. On success, `data` contains the wizard result and the written config path is the artifact; on timeout it fails with `setup form was not submitted within <N>s`.

### blackbox_discover_app

> Blackbox: open the app URL, detect+perform login, crawl routes, capture evidence, save discovery/graph/report JSON. No repo needed.

Full discovery pipeline. Saves `discovery.json`, `interaction_graph.json`, and a report JSON (all listed as artifacts). `data` is the discovery summary (route map, login probe result, and more). `success` is false when the crawl recorded errors.

### blackbox_detect_login

> Blackbox: detect the login form (username/password/submit locators) on the target: heuristics, no data-testid required.

Analyzes the login page (from `ui.auth.loginUrl`, default `/login`) without submitting credentials. `data.login` holds the detected locator expressions, `data.pattern` the page classification; the page screenshot is the artifact. `success` is false when no form was found.

### blackbox_perform_login

> Blackbox: detect the login form and actually log in with the given credentials; reports the landing route.

Performs the login (crawl capped at the login page plus the landing page). `data.login` is the detected form, `data.probe` the login probe result including `landed_route`. `success` mirrors whether the login succeeded.

### blackbox_crawl_routes

> Blackbox: login + safe BFS crawl; returns the route map (safeMode skips destructive links).

Data-focused alias of `blackbox_discover_app`. Returns `data.routeMap` and `data.skippedRoutes`.

### blackbox_analyze_page

> Blackbox: classify one page (login/dashboard/list/form/...); returns its interactive elements + evidence screenshot.

Takes `page_url` (route or absolute URL, default `/`). `data` is the full page digest (pattern, inputs, buttons, links, table/form/modal flags, locators); the screenshot is the artifact. `success` is false when the page rendered blank.

### blackbox_build_interaction_graph

> Blackbox: build the serializable interaction graph (page/form/table/modal nodes) from the saved discovery.

Requires a prior `blackbox_discover_app` (fails with `no discovery.json` otherwise). Returns the graph (`nodes`, `edges`) in `data` and writes `interaction_graph.json`.

### blackbox_generate_playwright_tests

> Blackbox: deterministically generate Playwright tests (smoke/auth/navigation/lists/forms) from the saved discovery.

Requires a prior discovery. The deterministic baseline is always generated; passing `prd_file` (markdown) appends PRD-driven semantic cases via the workspace LLM (needs `SUITEST_API_URL` and `SUITEST_API_KEY` so the server's LLM proxy is reachable). Returns the case manifest (`id`, `title`, `file`) in `data.cases` and the generated test files as artifacts.

### blackbox_run_playwright_tests

> Blackbox: execute the generated tests; per-case outcomes + video/screenshot evidence.

Requires a prior `blackbox_generate_playwright_tests` (fails with `no generated tests` otherwise). Executes each generated case (120 s timeout per test) and writes `blackbox_results.json`.

:::note
Publishing is not optional in this tool. When `SUITEST_API_URL` and `SUITEST_API_KEY` are set, it calls `blackbox_publish_results` automatically and a publish failure fails the tool: results must never stay local silently. The summary reports both the pass count and the publish outcome.
:::

### blackbox_collect_evidence

> Blackbox: index all evidence (screenshots, videos, traces, report JSONs).

Scans the output directory. `data` lists `screenshots`, `videos`, `traces`, and `reports`; everything is also returned as artifacts. See [Evidence](/docs/concepts/evidence/).

### blackbox_publish_results

> Publish the blackbox suite + latest run (video/screenshot evidence) into the Suitest web TCM. Needs project_id (or publish.projectId in config).

Uploads the generated cases (with steps and automation code) via bulk import and ingests the latest run with per-step screenshots and video artifacts. Also accepts a `suite_name` keyword argument (handler-level; not listed in the shared schema); the default suite name is derived from the target host.

Project binding rules:

- A configured `project_id` is validated first. A valid id is reused; a repairable id is rebound (and rewritten into the config file).
- A stale id with no unambiguous match **fails the publish** with `data.projectBinding.status = "missing"` and nothing is inserted, unless `recreate_project` is passed (or `publish.recreateProject` is set in the config).
- With no project configured, the server finds or creates a project by a slug derived from the target host (for example `myapp-example-com`), then the minted id is pinned back into the config so the next publish is an explicit-id retest.

On success, `data` contains `imported`, `run`, `projectBinding`, and `staleCases`.

### blackbox_summarize_findings

> Blackbox: one JSON summary (route map, bug candidates, test outcomes) for agent reasoning.

Requires a prior discovery. Merges the discovery, the interaction graph, and any test results into one report. `data` includes `routesDiscovered` and `bugCandidates`; the report JSON is the artifact.

## Calling the server by hand

Verify the handshake and tool list without an IDE:

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n' | npx -y @suiflex/suitest-mcp
```

The `initialize` response reports `serverInfo.name = "suitest-lifecycle"`. Tool calls use the standard `tools/call` method with `name` and `arguments`.
