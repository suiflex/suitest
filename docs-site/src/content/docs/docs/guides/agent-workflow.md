---
title: Testing from your IDE agent
description: Drive the full Suitest loop from Claude Code or Cursor. Generate tests, run them, read failures, fix code, and publish results.
---

Suitest exposes its whole testing lifecycle as MCP tools. Your IDE agent
(Claude Code, Cursor, or any MCP client) calls them in conversation: analyze
the project, generate test cases, run them in a real browser, and, when a run
fails, pull a compact failure bundle, fix the application code, and re-run.
Testing becomes something you ask for, not something you script.

## Prerequisites

- The Suitest MCP server connected to your IDE. See
  [Install the MCP server](/docs/install/mcp-server/).
- `SUITEST_API_URL` and `SUITEST_API_KEY` set in the server's `env` block.
  The server verifies them at startup against `GET /api/v1/api-keys/whoami`
  and refuses to start if either is missing or rejected. The key pins the
  workspace and project that every tool publishes into.
- Node 18+ and Python 3.11+ on the machine running the agent.

A minimal `.mcp.json`:

```json
{
  "mcpServers": {
    "suitest": {
      "command": "npx",
      "args": ["-y", "@suiflex/suitest-mcp"],
      "env": {
        "SUITEST_API_URL": "http://localhost:4000",
        "SUITEST_API_KEY": "sk_suitest_..."
      }
    }
  }
}
```

## The loop at a glance

```text
bootstrap_project / analyze_project     understand the app, write the config
        |
generate_test_cases                     PRD + plan + runnable test files
  (or generate_backend_tests /
       generate_frontend_tests)
        |
run_tests                               start app, wait ready, execute, report
        |
   all green? ──yes──> generate_report / sync_tcm / publish to the web TCM
        |
        no
        |
get_failure_context                     compact failure bundle (max 8 KB)
        |
agent edits the APPLICATION code
        |
run_tests again ──> green
```

## The repo-based tools

These 11 tools take `config_path` (default `suitest.config.json`). The other
11 tools are the `blackbox_*` family for URL-only testing, covered in
[Blackbox testing](/docs/guides/blackbox-testing/). The full list of all 22
tools with schemas is in the [MCP tools reference](/docs/reference/mcp-tools/).

| Tool | What it does |
|------|--------------|
| `bootstrap_project` | Opens a browser setup wizard (target URL, credentials, crawl scope, optional markdown PRD upload) and writes `suitest.config.json`. Call this first when no config exists. |
| `analyze_project` | Static-analyzes the target project. Lists endpoints (backend) or pages (frontend). |
| `generate_test_cases` | Analyzes, builds a PRD plus test plan, and exports runnable test files. |
| `generate_backend_tests` | Generates backend (requests) test files. Errors if the config mode is not `backend`. |
| `generate_frontend_tests` | Generates frontend (Playwright) test files. Errors if the config mode is not `frontend`. |
| `run_tests` | Runs the full lifecycle for whatever mode the config declares: start, wait ready, run, report. |
| `run_backend_tests` / `run_frontend_tests` | Same lifecycle, mode-guarded to one side. |
| `get_failure_context` | Returns the budgeted failure bundle for the last run. See [Failure context](/docs/guides/failure-context/). |
| `generate_report` | Re-surfaces the last run's report artifacts without re-running. |
| `sync_tcm` | Reports the TCM mirror (case and run counts plus file paths). |

Every tool returns the same envelope, so the agent always gets
machine-parseable output:

```json
{
  "success": true,
  "summary": "generated 12 test case(s) for frontend",
  "data": {},
  "artifacts": ["suitest-output/frontend/TC001_login_works.py"],
  "errors": []
}
```

Expected failures (bad config, target not ready) never raise. They come back
as `success: false` with `errors` filled in, so the agent can react instead of
crashing.

## Example prompts and what they trigger

**"Set up Suitest for this project."**
The agent calls `bootstrap_project` with `project_path` pointing at the repo.
A browser wizard opens for you to fill in the target URL, test credentials,
and crawl scope. The tool returns the path of the written
`suitest.config.json`. You can also write the config by hand: see the
[configuration reference](/docs/reference/configuration/).

**"What is testable in this app?"**
The agent calls `analyze_project`. For a backend config it returns the
detected endpoints; for a frontend config, the pages and whether they are
protected.

**"Generate tests for this app."**
The agent calls `generate_test_cases`. The envelope lists the generated cases
and the exported test files as artifacts. If your config mode is fixed, the
agent may use `generate_frontend_tests` or `generate_backend_tests` instead;
those error early on a mode mismatch instead of generating the wrong thing.

**"Run the tests."**
The agent calls `run_tests`. Suitest starts the app, waits for readiness,
executes every case in a real browser (frontend) or against the API
(backend), records evidence, and publishes cases, runs, and video to the web
TCM when API credentials are set.

**"Show me the last report."**
The agent calls `generate_report`, which returns the paths of `summary.md`,
`summary.json`, and `summary.html` from the last run without re-running
anything. `sync_tcm` answers "what is mirrored where" with case and run
counts.

## Closing the loop on a failure

This is the part that makes the agent workflow more than a test runner. A
realistic session:

```text
You:    Run the tests.
Agent:  run_tests(config_path="suitest.config.json")
        -> success=false, "9 case(s): 7 passed, 2 failed"

Agent:  get_failure_context(config_path="suitest.config.json")
        -> "2 failing case(s); context ready for repair"
        -> data.failure_context (markdown, <= 8 KB):
           Test user_can_submit_checkout failed at step 3/6.
           Error: TimeoutError: locator("#submit-btn") not found.
           DOM excerpt shows the button now renders as
           <button id="checkout-submit">.

Agent:  edits src/pages/Checkout.tsx so the submit button keeps its
        stable id, then:
        run_tests(config_path="suitest.config.json")
        -> success=true, "9 case(s): 9 passed"
```

The failure bundle contains the failed step, the error, a DOM excerpt around
the failed selector, console errors and warnings, non-2xx network calls, and
links to the screenshot and video evidence. It is deliberately small enough to
fit in an agent context window, so the agent can diagnose without opening
videos by hand. Details and the exact format are in
[Failure context](/docs/guides/failure-context/).

:::tip
The tool description itself tells the agent to call `get_failure_context`
whenever a run reports failing tests and it intends to fix the code. You
rarely need to ask for it explicitly; "fix the failing tests" is enough.
:::

## Re-runs and project bindings

Runs publish into a Suitest project identified by `publish.projectId` in the
config. If that project was deleted on the server, a re-run fails rather than
silently creating a new project. The run tools (`run_tests`,
`run_backend_tests`, `run_frontend_tests`) accept an explicit
`recreate_project: true` argument for that case; recreation never happens
implicitly.

## Where the results land

With `SUITEST_API_URL` and `SUITEST_API_KEY` set, every run publishes cases,
runs, per-step logs, and video evidence into the web TCM, where QA engineers
review and own the suite. The same loop also runs headless in CI with the
[GitHub Action](/docs/guides/ci-github-action/), using identical config and
exit codes.

## Next steps

- Test an app you have no repo for: [Blackbox testing](/docs/guides/blackbox-testing/)
- Add AI-assisted planning on your own model: [Bring your own LLM](/docs/guides/llm-setup/)
- Gate merges on test results: [CI with the GitHub Action](/docs/guides/ci-github-action/)
