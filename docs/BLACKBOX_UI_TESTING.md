# Blackbox DOM UI Testing (Zero + MCP)

> Status: BUILT (2026-07-02). Engine: `packages/lifecycle/src/suitest_lifecycle/blackbox/`.

Test any web app **without the repo** — a URL, test credentials, and a scope
are enough. Deterministic (ZERO tier, no LLM/API key required). One shared
engine, three consumers:

| Consumer | How |
|---|---|
| **Zero** | `suitest zero blackbox --url … --username … --password …` or `analysisSource: "blackbox"` in the config-driven lifecycle |
| **MCP**  | `blackbox_*` tools for Claude Code / Cursor / Codex (see below) |
| **LLM**  | `discovery.json` / `interaction_graph.json` are model-ready context |

## What it does

1. Opens a real Chromium, loads the target URL.
2. **Detects the login form heuristically** — email/username input, password
   input, remember-me, submit button — from labels, placeholders, `name`,
   `type`, `autocomplete`, ARIA and button text. `data-testid` is only the
   *first-priority* selector tier, **never a requirement**.
3. Logs in, verifies the redirect, records the error region on failure.
4. **Crawls** navbar/sidebar/menu routes (BFS) with caps (`maxDepth`,
   `maxRoutes`) and **safeMode** (default ON): never follows/clicks
   delete/remove/logout/billing/payment/publish/approve-style controls.
5. Per page: screenshot, console errors, network failures (5xx + failed
   requests), blank/crash detection, and a **pattern classification**:
   `login | dashboard | list | detail | form | modal | empty | error |
   forbidden | not_found | blank`.
6. Builds a serializable **interaction graph** (page/form/table/modal/action
   nodes; navigation/submit/validation edges).
7. **Generates deterministic Playwright tests** from the discovered locators:
   app loads, no critical console errors, login valid/invalid, landing page
   after login, navigation smoke over discovered routes, list/table renders,
   search filter, pagination, safe empty-submit form validation, modal
   dismiss. Generated files reuse the standard evidence wrapper (per-step
   screenshots, video, `.result.json`) and run through the normal runner —
   publish to a Suitest server works unchanged.
8. Writes `blackbox_report.json`: route map, evidence index, bug candidates.

## Selector strategy (priority order)

1. `data-testid` / `data-cy` / `data-test`
2. ARIA role + accessible name
3. `<label>` text
4. placeholder
5. input `name` / `type` / `autocomplete`
6. button/link text
7. stable CSS path
8. XPath (last resort only)

`crawl.ignoreTestIds: true` disables tier 1 — useful to validate that a suite
keeps working on apps with no testid convention.

## Safe form filling

Only used when a fill is required; forms are submitted **empty** for the
validation probe unless `testGeneration.allowMutation: true`:

| Field | Value |
|---|---|
| email | `qa+<token>@example.com` |
| password | from config credentials |
| text | `Test value` |
| number | `1` |
| date | today (ISO) |
| select | first non-empty option |
| textarea | `Automated QA test value` |

## Config (`suitest.config.json`)

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

`selectors.*` are optional manual overrides (raw CSS or a full
`page.…` expression) that beat detection. With a `ui.mode: "blackbox"`
section, a frontend lifecycle run automatically uses the blackbox engine
(`analysisSource` is implied). Example: `suitest-example/frontend/suitest.blackbox.config.json`.

## CLI (Zero)

```bash
suitest zero blackbox --url http://localhost:3000 \
    --username qa@example.com --password password123
suitest zero ui --config suitest.config.json        # alias
suitest zero blackbox --config suitest.config.json --max-routes 30
suitest zero blackbox --url … --headed --record-video
suitest zero blackbox --url … --discover-only        # stop after discovery/graph
suitest test --config suitest.config.json            # full lifecycle (blackbox via ui section)
suitest mcp                                          # stdio MCP server
```

## MCP tools

All accept `{config_path?, url?, username?, password?, max_routes?}`; state is
persisted under the output dir so stages compose across calls:

| Tool | Purpose |
|---|---|
| `blackbox_discover_app` | login + crawl + evidence; writes `discovery.json`, `interaction_graph.json`, `blackbox_report.json` |
| `blackbox_detect_login` | login-form locators only (no credentials needed) |
| `blackbox_perform_login` | detect + actually log in; landing route |
| `blackbox_crawl_routes` | route map focus |
| `blackbox_analyze_page` | classify one route (`page_url` param) |
| `blackbox_build_interaction_graph` | graph from saved discovery |
| `blackbox_generate_playwright_tests` | deterministic test files |
| `blackbox_run_playwright_tests` | execute; outcomes + evidence |
| `blackbox_collect_evidence` | index screenshots/videos/traces/reports |
| `blackbox_summarize_findings` | route map + bug candidates + results |
| `blackbox_publish_results` | push the suite + latest run (video/screenshot evidence) into the Suitest web TCM — no `project_id` needed: the server finds-or-creates a project from the target host slug. **`blackbox_run_playwright_tests` calls this automatically** whenever `SUITEST_API_URL`/`SUITEST_API_KEY` are set; a publish failure fails the run stage (results never stay local silently) |
| `bootstrap_project` | TestSprite-style browser setup wizard → writes `suitest.config.json` (+ PRD.md) |

## Evidence layout

```
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
│       └── videos/…
└── reports/blackbox_report.json    # route map, bug candidates, summary
```

## PRD upload flow (TestSprite parity)

Bring a **markdown** PRD (that format is required) and the plan becomes
requirement-driven on top of the deterministic baseline:

```bash
suitest zero blackbox --url http://localhost:3000 \
    --username qa@example.com --password password123 --prd PRD.md
```

Or config: top-level `"prdFile": "PRD.md"`. MCP:
`blackbox_generate_playwright_tests` accepts `prd_file`.

Flow: `prd_ingest` parses the markdown (headings → features, bullets →
requirements; artifact `prd_ingest.json`) → the workspace LLM (via the
server's `/llm/complete` proxy, same `SUITEST_API_KEY`) plans semantic cases
against the DISCOVERED routes/locators → each case's Playwright body is
LLM-written and statically validated (no imports, no `re`, no
`to_have_url`/`wait_for_url`, must compile) — a body that fails validation
degrades to a safe route-render probe so the PRD case never disappears.
Empty/fresh installs are handled: the planner is told to prefer empty-state /
validation / auth flows and creates-own-data flows; mutations stay off unless
`testGeneration.allowMutation`.

Quality envelope (honest): the deterministic baseline is stable; PRD-case
pass-rate depends on the workspace model. A consistent strong model passes
clean; routed gateways that load-balance across upstreams produce 0–5
literal-guess assertion failures per ~13 PRD cases — visible as FAILED with
evidence, never silent.

## Guarantees / limits

* Zero mode needs **no LLM and no API key**; MCP tools run everywhere the
  lifecycle MCP server runs.
* The old suitest-example testid convention is *only* selector tier 1;
  removing every testid from an app must not break login or generation
  (covered by `tests/test_blackbox.py` + the `ignoreTestIds` flag).
* SafeMode is ON by default; destructive links are recorded in
  `skippedRoutes`, never visited.
* SPA routes reachable only via JS `navigate()` (no `<a href>`) are not yet
  discovered — same limitation as the crawl analyzer.
