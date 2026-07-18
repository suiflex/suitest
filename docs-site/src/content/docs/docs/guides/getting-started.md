---
title: Getting started
description: Go from zero to your first agent-generated test run in about ten minutes, with or without a Suitest server.
---

This is the 10-minute path: pick an install route, run one setup command,
restart your IDE, and ask the agent to test your app.

## Pick your route

| Route | What you get | Needs |
|-------|--------------|-------|
| **Local bundle** | The full platform on your laptop — dashboard + SQLite + MCP wiring in one command, no Docker | Node 18+, uv |
| **MCP server only** | Your IDE agent generates and runs tests; results stay on disk in your repo | Node 18+, Python 3.11+ |
| **Full platform (server)** | Everything above on Postgres + object storage, shared by the whole team | Docker |

Solo and want the dashboard? `npx @suiflex/suitest onboard` does all of
Route 1 for you and boots the dashboard — see
[Local bundle](/docs/install/local-bundle/). Otherwise start with the MCP
server; you can add a platform later and reconnect with one command.

## Route 1: MCP server in your IDE

### 1. Run init

In the root of the project you want to test:

```bash
npx -y @suiflex/suitest-mcp init
```

`init` detects your IDE (Claude Code or Cursor from project markers; pass
`--ide windsurf` for Windsurf) and your framework (Next.js, Nuxt, SvelteKit,
Vite, Vue, Express, Django), then asks one question: local or server. Pick **local** for now; it
needs no API key.

It writes two files:

- `suitest.config.json`: the project's test config (mode, base URL)
- your IDE's MCP config, with a `suitest` entry merged in alongside your
  existing MCP servers

Full flag reference and per-IDE details:
[Install the MCP server](/docs/install/mcp-server/).

### 2. Restart your IDE

MCP configs are read at startup. Restart Claude Code, Cursor, or Windsurf so
the `suitest` server appears in the agent's tool list.

### 3. Start your app

The agent tests a running app. Start it as usual, for example:

```bash
npm run dev   # your app on http://localhost:3000
```

### 4. Give the agent its first prompt

In your IDE's agent chat:

> Test my app at http://localhost:3000

The agent picks up the Suitest tools and works through the lifecycle:

1. `analyze_project`: statically analyzes the repo (pages or endpoints)
2. `generate_test_cases`: writes a test plan and runnable test files
3. `run_tests`: executes them against your running app with evidence
4. `generate_report`: emits a human-readable summary

### What you get

Everything lands under `suitest-output/` in your project:

- **Cases**: a test plan plus runnable `TC001_*.py` style test files
- **A run**: pass/fail per case, recorded in `tcm/cases.json` and
  `tcm/runs.json`
- **Evidence**: per-step screenshots and video for frontend runs, captured
  during execution
- **A report**: `reports/summary.md`, `summary.json`, and `summary.html`

If something fails, ask the agent to call `get_failure_context`: it returns an
agent-readable bundle of the failing cases from the last run so the agent can
propose a fix. See [Failure context](/docs/guides/failure-context/).

:::tip
No repo access to the app you want to test? The blackbox engine tests any web
app from a URL and test credentials alone. See
[Blackbox testing](/docs/guides/blackbox-testing/).
:::

## Route 2: full platform

Run the platform when you want the team-facing web TCM: shared test cases,
run history, evidence playback, defects, and analytics.

### 1. Boot it

```bash
git clone https://github.com/suiflex/suitest && cd suitest
cp .env.example .env    # set secrets + super-admin, see the install guide
docker compose -f infra/docker/docker-compose.yml --profile zero up -d
```

Open <http://localhost:3000> and log in with the super-admin credentials from
your `.env`. Full walkthrough, including every `.env` value worth changing:
[Install with Docker Compose](/docs/install/docker/).

### 2. Connect your IDE to it

Create an API key in the web UI, then re-run init in server mode:

```bash
npx -y @suiflex/suitest-mcp init --mode server \
  --api-url http://localhost:4000 --api-key sk_suitest_xxx
```

From now on, the same agent workflow publishes cases, runs, and evidence into
the web TCM instead of keeping them only on disk.

### 3. Same first prompt

Restart the IDE and ask again:

> Test my app at http://localhost:3000

When the run finishes, open the web UI: the generated cases appear under
**Test Cases**, and the run detail page shows per-step results with
screenshots and video.

## Where to next

- [Tutorial: your first run](/docs/guides/tutorial/): a full worked example,
  including a failing test, `get_failure_context`, the fix, and publishing
- [How it works](/docs/concepts/how-it-works/): the architecture behind the
  lifecycle
- [Agent workflow](/docs/guides/agent-workflow/): prompts and patterns for
  driving the agent
- [MCP tools reference](/docs/reference/mcp-tools/): every tool, argument by
  argument
- [Configuration reference](/docs/reference/configuration/): everything
  `suitest.config.json` supports
- [FAQ](/docs/help/faq/) and [Troubleshooting](/docs/help/troubleshooting/)
