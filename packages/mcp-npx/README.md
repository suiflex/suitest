# @suitest/mcp

Run the [Suitest](https://github.com/suiflex/suitest) MCP server with a single command:

```bash
npx -y @suitest/mcp
```

Suitest turns your IDE agent (Claude Code, Cursor, Codex — anything that speaks
[MCP](https://modelcontextprotocol.io)) into a QA automation engineer: analyze a
project, generate runnable tests, execute them with evidence (video, per-step
screenshots), and publish results to a Suitest server.

It includes a **blackbox DOM testing engine** — test any web app with no repo
access at all: a URL, test credentials, and a scope are enough. Deterministic,
no LLM key required.

## Requirements

- Node.js ≥ 18 (to run this launcher)
- Python ≥ 3.11 on `PATH` (the server itself; stdlib-only, nothing to install).
  Override the interpreter with `SUITEST_PYTHON=/path/to/python`.
- Frontend test execution provisions Playwright/Chromium on demand.

## IDE setup

Add to your project's `.mcp.json` (Claude Code) or the equivalent MCP config:

```json
{
  "mcpServers": {
    "suitest": {
      "command": "npx",
      "args": ["-y", "@suitest/mcp"],
      "env": {
        "SUITEST_API_URL": "http://localhost:4000",
        "SUITEST_API_KEY": "sk_suitest_…"
      }
    }
  }
}
```

`SUITEST_API_URL`/`SUITEST_API_KEY` connect the pipeline to a self-hosted
Suitest server so cases, runs, and evidence land in the web TCM (and unlock
LLM-assisted generation through the server's `/llm/complete` proxy). Without
them the tools still work — results stay local under `suitest-output/`.

## What the agent gets

21 tools, three workflows:

| Workflow | Tools | Needs |
|---|---|---|
| Repo-based lifecycle | `analyze_project`, `generate_test_cases`, `run_tests`, `generate_report`, … | a checkout + `suitest.config.json` |
| Blackbox (no repo) | `bootstrap_project` (browser setup wizard), `blackbox_discover_app`, `blackbox_generate_playwright_tests`, `blackbox_run_playwright_tests`, `blackbox_summarize_findings`, … | a URL + credentials |
| PRD-driven | `blackbox_generate_playwright_tests` with `prd_file` (markdown) | a PRD + a workspace LLM |

Full tool reference: [docs/MCP_PLUGINS.md](https://github.com/suiflex/suitest/blob/main/docs/MCP_PLUGINS.md)
and [docs/BLACKBOX_UI_TESTING.md](https://github.com/suiflex/suitest/blob/main/docs/BLACKBOX_UI_TESTING.md).

## CLI

```bash
npx -y @suitest/mcp --help      # usage + config snippet
npx -y @suitest/mcp --version
```

## How it works

This package bundles the `suitest_lifecycle` Python module (stdlib-only) and a
thin Node launcher that starts it as a stdio MCP server. No pip install, no
virtualenv, no daemon.

## License

Apache-2.0 — see [LICENSE](./LICENSE).
