---
title: Blackbox testing from a URL
description: Test any running web app without repo access. Discover, crawl, generate and run Playwright tests from a URL and test credentials.
---

Blackbox mode tests a web app you can reach but whose code you do not have: a
staging URL, a third-party app, a legacy system. A URL, test credentials, and
a crawl scope are enough. The engine is deterministic, needs no LLM and no API
key, and is exposed three ways: the `suitest zero blackbox` CLI, the
`blackbox_*` MCP tools, and the config-driven lifecycle.

## What the engine does

1. Opens a real Chromium and loads the target URL.
2. Detects the login form heuristically from labels, placeholders, `name`,
   `type`, `autocomplete`, ARIA attributes, and button text. `data-testid` is
   only the first-priority selector tier, never a requirement.
3. Logs in, verifies the redirect, and records the error region on failure.
4. Crawls navbar, sidebar, and menu routes (BFS) with caps (`maxDepth`,
   `maxRoutes`). Safe mode is on by default: delete, remove, logout, billing,
   payment, publish, and approve style controls are never followed.
5. Per page: screenshot, console errors, network failures, blank or crash
   detection, and a pattern classification (`login`, `dashboard`, `list`,
   `detail`, `form`, `modal`, `empty`, `error`, `forbidden`, `not_found`,
   `blank`).
6. Builds a serializable interaction graph (page, form, table, and modal
   nodes with navigation, submit, and validation edges).
7. Generates deterministic Playwright tests from the discovered locators:
   app loads, no critical console errors, login valid and invalid, landing
   page after login, navigation smoke, list rendering, search filter,
   pagination, safe empty-submit form validation, modal dismiss.
8. Writes `blackbox_report.json` with the route map, evidence index, and bug
   candidates.

## Quick start: CLI

```bash
suitest zero blackbox --url http://localhost:3000 \
    --username qa@example.com --password password123
```

This runs the full pipeline: discover, generate, run, summarize. It prints a
per-stage summary and a JSON findings digest, and exits `0` when everything
passed, `1` otherwise. `suitest zero ui` is an alias. See the
[CLI reference](/docs/reference/cli/) for the full command surface.

| Flag | Meaning |
|------|---------|
| `--url` | Target app URL |
| `--config` | `suitest.config.json` with a `ui` section (alternative to `--url`) |
| `--username` / `--password` | Test credentials |
| `--max-routes` | Crawl route cap (default 30) |
| `--max-depth` | Crawl depth cap (default 3) |
| `--headed` | Run the browser headed |
| `--record-video` | Record video evidence for generated tests |
| `--no-safe-mode` | Allow destructive links and actions (safe mode is on by default) |
| `--prd` | Markdown PRD file for a requirement-driven plan via the workspace LLM |
| `--discover-only` | Stop after discovery and graph, skip generation and execution |

## Quick start: from an IDE agent

Tell your agent: "Test the app at http://localhost:3000 with user
qa@example.com". It chains the `blackbox_*` MCP tools. All of them accept the
same structured arguments (`config_path`, `url`, `username`, `password`,
`max_routes`), and state persists under the output directory, so stages
compose across separate calls.

| Tool | Purpose |
|------|---------|
| `blackbox_discover_app` | Open the app, detect and perform login, crawl routes, capture evidence, save `discovery.json`, `interaction_graph.json`, and `blackbox_report.json` |
| `blackbox_detect_login` | Detect the login form locators only, no credentials needed |
| `blackbox_perform_login` | Detect the form and actually log in, reporting the landing route |
| `blackbox_crawl_routes` | Login plus safe BFS crawl, returning the route map |
| `blackbox_analyze_page` | Classify one page and list its interactive elements (`page_url` argument) |
| `blackbox_build_interaction_graph` | Build the serializable interaction graph from the saved discovery |
| `blackbox_generate_playwright_tests` | Deterministically generate Playwright tests from the saved discovery (accepts `prd_file`) |
| `blackbox_run_playwright_tests` | Execute the generated tests with per-case outcomes and video and screenshot evidence |
| `blackbox_collect_evidence` | Index all evidence: screenshots, videos, traces, report JSONs |
| `blackbox_publish_results` | Publish the suite and latest run into the Suitest web TCM (accepts `project_id` and `recreate_project`) |
| `blackbox_summarize_findings` | One JSON summary of the route map, bug candidates, and test outcomes for agent reasoning |

There is no fixed order beyond the data flow: discovery must exist before
graph, generation, or execution. `blackbox_discover_app` is the orchestrated
entry point that produces everything the later stages read.

## Selector strategy

Locators are chosen in priority order:

1. `data-testid` / `data-cy` / `data-test`
2. ARIA role plus accessible name
3. `<label>` text
4. placeholder
5. input `name` / `type` / `autocomplete`
6. button or link text
7. stable CSS path
8. XPath (last resort only)

Set `crawl.ignoreTestIds: true` to disable tier 1, which is useful for
validating that a suite keeps working on apps with no testid convention.

## Configuration

The same engine runs from a config file. With a `ui.mode: "blackbox"` section,
a frontend lifecycle run automatically uses the blackbox engine:

```jsonc
{
  "mode": "frontend",
  "baseUrl": "http://localhost:3000",
  "ui": {
    "mode": "blackbox",
    "targetUrl": "http://localhost:3000",
    "auth": { "strategy": "form", "loginUrl": "/login",
              "username": "qa@example.com", "password": "password123" },
    "crawl": { "maxDepth": 3, "maxRoutes": 30, "maxActionsPerPage": 20,
               "include": [], "exclude": ["/logout", "/billing", "/payment"],
               "safeMode": true, "ignoreTestIds": false },
    "selectors": { "loginUsername": "", "loginPassword": "", "loginSubmit": "" },
    "testGeneration": { "includeSmoke": true, "includeAuth": true,
                        "includeNavigation": true, "includeForms": true,
                        "includeTables": true, "allowMutation": false }
  }
}
```

`selectors.*` are optional manual overrides that beat detection. Forms are
submitted empty for the validation probe unless
`testGeneration.allowMutation: true`. Full schema:
[configuration reference](/docs/reference/configuration/).

## PRD-driven planning

Bring a markdown PRD and the plan becomes requirement-driven on top of the
deterministic baseline:

```bash
suitest zero blackbox --url http://localhost:3000 \
    --username qa@example.com --password password123 --prd PRD.md
```

Or set top-level `"prdFile": "PRD.md"` in the config, or pass `prd_file` to
`blackbox_generate_playwright_tests`. The PRD is parsed into features and
requirements, the workspace LLM plans semantic cases against the discovered
routes and locators, and each generated Playwright body is statically
validated. A body that fails validation degrades to a safe route-render probe,
so the PRD case never disappears. This path needs an LLM: see
[Bring your own LLM](/docs/guides/llm-setup/).

## Evidence layout

```text
suitest-output/
├── frontend/
│   ├── TCxxx_*.py                  # generated tests (evidence wrapper included)
│   ├── TCxxx.result.json           # per-test steps + video + screenshot
│   └── tmp/
│       ├── blackbox/*.png          # per-route crawl screenshots
│       ├── discovery.json
│       ├── interaction_graph.json
│       ├── blackbox_cases.json
│       ├── blackbox_results.json
│       └── videos/
└── reports/blackbox_report.json    # route map, bug candidates, summary
```

Generated files reuse the standard evidence wrapper (per-step screenshots,
video, `.result.json`) and run through the normal runner. More on evidence:
[Evidence](/docs/concepts/evidence/).

## Publishing to the web TCM

`blackbox_publish_results` pushes the suite and the latest run, including
video and screenshot evidence, into the Suitest web TCM. No `project_id` is
required: the server finds or creates a project from the target host slug.

:::note
Whenever `SUITEST_API_URL` and `SUITEST_API_KEY` are set,
`blackbox_run_playwright_tests` publishes automatically, and a publish
failure fails the run stage. Results never stay local silently.
:::

## Guarantees and limits

- Zero mode needs no LLM and no API key.
- Safe mode is on by default; destructive links are recorded in
  `skippedRoutes` and never visited.
- Removing every testid from an app must not break login or generation;
  testids are only selector tier 1.
- SPA routes reachable only via a JavaScript `navigate()` call with no
  `<a href>` are not yet discovered.
