---
title: How Suitest works
description: The Suitest pipeline from bootstrap to report, the MCP and CLI entry points, and how the API, dashboard, runner, and MCP server fit together.
---

Suitest is an MCP native testing platform. You point it at an application, it analyzes what that application is, generates test cases, runs them deterministically through MCP providers, records evidence, and publishes everything to a managed dashboard. An AI agent in your IDE can drive the whole loop, and so can you from a terminal.

This page explains the pipeline and the architecture behind it. For the entity model see [Data model](/docs/concepts/data-model/), for what gets recorded see [Evidence](/docs/concepts/evidence/).

## The pipeline

Every session moves through the same stages, whether an IDE agent or the CLI is driving:

```text
bootstrap -> analyze / crawl -> plan -> generate cases -> run -> evidence -> publish -> report
```

1. **Bootstrap.** Suitest prepares the environment: a browser setup wizard installs what the blackbox engine needs, and your entry point supplies the target (a repo path, or a URL plus test credentials) along with options such as route and depth caps.

2. **Analyze or crawl.** Suitest works out what the app is before deciding what to test. Two modes feed the same downstream stages:
   - **Repo based:** Suitest reads the project source, detects the frontend and backend split, and inspects the API surface (including OpenAPI definitions).
   - **Blackbox:** no repo needed. Give Suitest a URL and test credentials; it detects the login form, logs in, crawls routes safely, analyzes each page's DOM, and builds an interaction graph. Safe mode is on by default, so destructive links and actions are skipped unless you explicitly disable it. See [Blackbox testing](/docs/guides/blackbox-testing/).

3. **Plan.** The analysis becomes a testing plan. Planning is rule based and deterministic; when your workspace has an LLM configured, a Markdown PRD can drive the plan instead.

4. **Generate cases.** The plan becomes structured test cases (title, slug, steps, expected results) plus executable Playwright specs. Deterministic generators (OpenAPI parser, browser recorder, crawler based generation) work at every tier; an LLM adds richer cases and code generation on top. See [Capability tiers](/docs/reference/tiers/).

5. **Run.** Execution is always deterministic. On the platform, the runner dispatches each test step through an MCP provider: `playwright` for real browser steps, `api-http` for HTTP calls, `postgres` for database verification. Live status streams to the run detail page over WebSocket, and runs can be cancelled or rerun. The runner is the only component that decides pass or fail. Never the LLM.

6. **Evidence.** Screenshots, per test video, DOM snapshots, console logs, and network captures are uploaded to object storage and attached to the exact run step that produced them. See [Evidence](/docs/concepts/evidence/).

7. **Publish.** Optionally, cases, runs, and evidence are persisted to your Suitest instance using an API key. Without a key everything still works; results stay local under `suitest-output/`.

8. **Report.** The run is condensed into something a human, or an agent, actually reads: a structured report from the CLI and MCP tools, plus dashboards, pass rate analytics, and a traceability matrix in the web app. Failures can auto file rule based defects.

## Two entry points

Both entry points are thin wrappers over the same lifecycle package, so they produce identical results.

### IDE agent via the MCP server

The Suitest MCP server is a stdio JSON-RPC server that exposes the full lifecycle as tools: repo analysis (`analyze_project`, `generate_test_cases`, `run_tests`, `generate_report`, `sync_tcm`), the blackbox engine (`blackbox_discover_app` and its siblings), and PRD ingestion. Add it to your IDE's MCP config and the agent takes it from there:

```bash
# npm launcher
npx -y @suiflex/suitest-mcp

# or via uv
uvx --from suiflex-suitest-lifecycle suitest-mcp
```

A typical agent session looks like this:

```text
"Please test the checkout flow"           (you, in your IDE)
  -> agent: analyze_project / blackbox_discover_app
  -> agent: generate_test_cases
  -> agent: run_tests
  -> FAIL on step 3
  -> agent: reads the failure output and evidence
  -> agent: edits application code
  -> agent: run_tests                     -> PASS
  -> agent: sync_tcm                      (publish to the platform)
```

See [Install the MCP server](/docs/install/mcp-server/), the [MCP tools reference](/docs/reference/mcp-tools/), and the [Agent workflow guide](/docs/guides/agent-workflow/).

### CLI

The same pipeline from a terminal or CI job:

```bash
# Blackbox: test a running app by URL, no repo needed
suitest zero blackbox --url https://staging.example.com \
  --username qa@example.com --password '...'

# Run from a config file
suitest test --config suitest.config.json

# Start the MCP server on stdio
suitest mcp
```

Set `SUITEST_API_URL` and `SUITEST_API_KEY` to publish results to your instance; omit them to keep everything local. See the [CLI reference](/docs/reference/cli/) and [CI with GitHub Actions](/docs/guides/ci-github-action/).

## Architecture

```text
        IDE agent                        You / CI
   (Claude Code, Cursor, ...)           (terminal)
            |                               |
            v                               v
     +--------------+               +--------------+
     |  MCP server  |               |     CLI      |
     |   (stdio)    |               |  (suitest)   |
     +------+-------+               +------+-------+
            |     same lifecycle package   |
            +--------------+---------------+
                           |  publish (REST, API key)
                           v
 +-----------+   REST + WebSocket   +---------------+
 |    Web    | <------------------> |     API       |
 | dashboard |                      |   (FastAPI)   |
 +-----------+                      +-------+-------+
                                            |
            +----------------+--------------+---------------+
            v                v                              v
      +----------+     +----------+   run jobs      +---------------+
      | Postgres |     |  Redis   | --------------> |    Runner     |
      +----------+     +----------+                 | (ARQ workers) |
            ^                                       +-------+-------+
            |          +------------+   artifacts           |
            +----------| MinIO / S3 | <---------------------+
                       +------------+                       |
                                          per step MCP calls|
                                                            v
                                    +------------------------------------+
                                    |           MCP providers            |
                                    |  playwright   api-http   postgres  |
                                    +------------------------------------+
```

The moving parts:

| Component | What it is | What it does |
|-----------|-----------|--------------|
| **API** | FastAPI service | REST endpoints, WebSocket log streaming, auth, per workspace capability resolution, integrations |
| **Web dashboard** | React SPA (Vite) | Test case management, live run detail with video, dashboards, analytics, defects, traceability, settings |
| **Runner** | ARQ worker processes | Dequeues run jobs from Redis, dispatches each step to an MCP provider, streams logs, uploads artifacts |
| **MCP server** | stdio JSON-RPC process | Exposes the lifecycle (analyze, generate, run, publish) as MCP tools for IDE agents |
| **Postgres** | Database | All entities: workspaces, cases, runs, defects, and more |
| **Redis** | Queue and pub/sub | Run job queue for the runner, live log fan out |
| **MinIO / S3** | Object storage | Run artifacts: screenshots, video, logs, captures |

See the install guides for [Docker](/docs/install/docker/), [Kubernetes](/docs/install/kubernetes/), and [from source](/docs/install/from-source/).

## MCP in both directions

Suitest's architectural signature is that it sits on both sides of the Model Context Protocol:

- **As an MCP server**, it gives IDE agents typed tools for the whole testing lifecycle.
- **As an MCP client host**, its runner executes every test step through an MCP provider. Browser clicks, HTTP requests, and database queries all flow through typed tool calls.

Each test step declares a `target_kind` (for example `FE_WEB`, `BE_REST`, `DATA`) and optionally a specific `mcp_provider`. When the provider is left blank, a routing table maps the target kind to a default: `FE_WEB` routes to the Playwright provider, `BE_REST` to the HTTP provider, `DATA` to the Postgres provider. A single test case can mix providers, for example seed a row in Postgres, call an API, then verify the result in a real browser.

Bundled providers ship in the image and are pre registered in every workspace: `playwright`, `api-http`, and `postgres` are the primary three, with `graphql`, `mysql`, `mongo`, `kubernetes`, and `grpc` also available. You can register your own MCP servers from the dashboard.

## Deterministic core, optional AI

Suitest is AI assisted, not AI dependent. The deterministic pipeline (crawl, generate, run, evidence, report) is fully functional with no LLM at all. Configuring an LLM for your workspace stacks AI features on top: PRD driven planning, LLM code generation, failure diagnosis, and agent chat.

| Stage | Without an LLM (ZERO tier) | With an LLM (LOCAL / CLOUD) |
|-------|----------------------------|------------------------------|
| Analyze | Full: deterministic crawl, OpenAPI, DOM | Same, plus semantic understanding |
| Plan | Rule based plan | PRD driven planning |
| Generate | Recorder, crawler, OpenAPI generators | Plus LLM code generation and richer cases |
| Run | Full, always deterministic | Identical: AI never decides pass or fail |
| Evidence | Full | Identical |
| Report | Full | Plus AI diagnosis |

The right column never replaces the left; it only adds to it. How the tier is resolved and what each tier unlocks is covered in [Capability tiers](/docs/reference/tiers/).

:::tip
The fastest way to see the pipeline end to end is the [getting started guide](/docs/guides/getting-started/): one blackbox run against a URL, no repo and no LLM required.
:::

## Next steps

- [Getting started](/docs/guides/getting-started/): first run in minutes
- [Data model](/docs/concepts/data-model/): what all these entities are
- [Evidence](/docs/concepts/evidence/): what gets recorded and where it lives
- [Failure context](/docs/guides/failure-context/): how agents consume failures
