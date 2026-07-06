---
title: "Tutorial: your first run"
description: A full first run against a Next.js app, from init to a failing test, the fix, a green re-run, and publishing.
---

This tutorial walks the complete loop once, end to end: set up the MCP server
against a Next.js app, let the agent generate and run tests, hit a real
failure, use `get_failure_context` to fix it, re-run green, and publish the
results to a Suitest server.

Command output in this tutorial is illustrative. Your paths, counts, and case
names will differ; the shapes will not.

## Prerequisites

- A Next.js app you can run locally (any web app works; Next.js, Vite,
  Express, and Django are auto-detected)
- Node 18+ and Python 3.11+ on `PATH`
- An MCP-capable IDE agent: Claude Code, Cursor, or Windsurf

## Step 1: init

From the app's repository root:

```bash
npx -y @suiflex/suitest-mcp init
```

Example output:

```bash
Mode: 1) Local (SQLite, no server)  2) Connect a server  [1]: 1

Done: claude-code, local mode, nextjs app.
  wrote /home/you/acme-shop/.mcp.json
  wrote /home/you/acme-shop/suitest.config.json
Restart your IDE, then tell the agent: "test my app".
```

Two files were written. `suitest.config.json` seeds the lifecycle with the
detected framework defaults:

```json
{
  "mode": "frontend",
  "projectName": "acme-shop",
  "projectPath": ".",
  "baseUrl": "http://localhost:3000",
  "server": {
    "autostart": false,
    "startCommand": ""
  }
}
```

And the IDE's MCP config gained a `suitest` entry. In local mode it carries
`SUITEST_MODE=local` and no credentials; everything stays on disk.

Restart your IDE so it picks up the new MCP server, then start your app:

```bash
npm run dev   # serving http://localhost:3000
```

## Step 2: generate test cases

In the agent chat:

> Test my app at http://localhost:3000

The agent first calls `analyze_project`, which statically analyzes the repo.
Every Suitest tool returns the same envelope. Example result:

```json
{
  "success": true,
  "summary": "analyzed frontend: 6 pages",
  "data": { "pages": ["/", "/login", "/products", "/cart", "..."] },
  "artifacts": [],
  "errors": []
}
```

Then it calls `generate_test_cases`, which turns the analysis into a PRD, a
test plan, and runnable test files. Example result:

```json
{
  "success": true,
  "summary": "generated 8 test case(s) for frontend",
  "data": { "cases": ["..."] },
  "artifacts": [
    "suitest-output/frontend/standard_prd.json",
    "suitest-output/frontend/suitest_frontend_test_plan.json",
    "suitest-output/frontend/tmp/code_summary.json",
    "suitest-output/frontend/TC001_login_with_valid_credentials.py",
    "suitest-output/frontend/TC002_login_rejects_wrong_password.py",
    "suitest-output/frontend/TC003_add_product_to_cart.py"
  ],
  "errors": []
}
```

The test files are ordinary Playwright-driving Python scripts checked into
`suitest-output/frontend/`. Open one; you can read and edit it like any test
you would write yourself.

## Step 3: run, and hit a failure

The agent calls `run_tests`, which executes the generated cases against your
running app and records evidence (per-step screenshots, and video for browser
runs). Example result:

```json
{
  "success": false,
  "summary": "7 passed, 1 failed (8 total)",
  "data": { "results": ["..."] },
  "artifacts": ["suitest-output/reports/summary.md"],
  "errors": ["TC003_add_product_to_cart failed"]
}
```

One case failed. This is the interesting part.

## Step 4: get the failure context

The agent calls `get_failure_context`. It does not re-run anything: it reads
the stored results of the last run and returns an agent-readable repair
bundle. Example result:

```json
{
  "success": true,
  "summary": "1 failing case(s); context ready for repair",
  "data": {
    "failed_cases": 1,
    "failure_context": "## TC003_add_product_to_cart\n\n- step: click 'Add to cart'\n- error: locator 'button[data-testid=add-to-cart]' not found\n- page: /products/42\n..."
  },
  "artifacts": [],
  "errors": []
}
```

With that context in the conversation, the agent can see exactly which step
failed, on which page, with which selector or assertion. Two outcomes are
possible:

- **The test is wrong** (stale selector, bad assumption): the agent edits the
  generated test file under `suitest-output/frontend/`.
- **The app is wrong** (a real bug): the agent points at the offending code in
  your repo and proposes a fix.

In this example the app renamed the button's test id, so the agent updates the
selector in `TC003_add_product_to_cart.py`. See
[Failure context](/docs/guides/failure-context/) for how to steer this step.

## Step 5: re-run green

Ask the agent to run again, or just say "re-run the tests". It calls
`run_tests` once more. Example result:

```json
{
  "success": true,
  "summary": "8 passed, 0 failed (8 total)",
  "data": { "results": ["..."] },
  "artifacts": ["suitest-output/reports/summary.md"],
  "errors": []
}
```

`generate_report` re-emits the report bundle from the stored summary without
re-running:

```json
{
  "success": true,
  "summary": "report available at suitest-output/reports",
  "artifacts": [
    "suitest-output/reports/summary.md",
    "suitest-output/reports/summary.json",
    "suitest-output/reports/summary.html",
    "suitest-output/frontend/tmp/raw_report.md"
  ],
  "errors": []
}
```

Open `suitest-output/reports/summary.html` in a browser for the full
per-case, per-step view with evidence links.

## Step 6: publish to a Suitest server

So far everything lives on disk. To share cases, runs, and evidence with your
team, connect the MCP server to a running Suitest platform (see
[Install with Docker Compose](/docs/install/docker/) if you do not have one).

Create an API key in the web UI, then switch the project to server mode:

```bash
npx -y @suiflex/suitest-mcp init --mode server \
  --api-url http://localhost:4000 --api-key sk_suitest_xxx --yes
```

This rewrites the `suitest` MCP entry with `SUITEST_API_URL` and
`SUITEST_API_KEY`; your `suitest.config.json` is kept as-is. Restart the IDE
and ask the agent to run the tests again. With server credentials present,
the run publishes cases, results, and evidence into the web TCM.

`sync_tcm` reports the local source-of-truth mirror at any time. Example
result:

```json
{
  "success": true,
  "summary": "TCM mirror: 8 case(s), 2 run(s)",
  "data": { "cases": 8, "runs": 2 },
  "artifacts": [
    "suitest-output/tcm/cases.json",
    "suitest-output/tcm/runs.json"
  ],
  "errors": []
}
```

Open the web UI: the eight cases appear under **Test Cases**, and the run
detail page plays back the evidence per step.

## What you just did

1. `init` wired the MCP server into your IDE and scaffolded the config
2. The agent analyzed the repo and generated runnable cases
3. A run failed; `get_failure_context` gave the agent the exact failing step
4. One fix later, the suite ran green
5. Server mode published the whole thing to the team TCM

## Next steps

- [Agent workflow](/docs/guides/agent-workflow/): prompt patterns for daily use
- [Blackbox testing](/docs/guides/blackbox-testing/): test apps you have no
  repo for
- [MCP tools reference](/docs/reference/mcp-tools/): all tools and arguments
- [Configuration reference](/docs/reference/configuration/): tune
  `suitest.config.json`, including app autostart
- [CI with GitHub Actions](/docs/guides/ci-github-action/): gate merges on the
  same lifecycle
