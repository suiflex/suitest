---
title: Troubleshooting
description: Fixes for the most common Suitest problems, from MCP servers missing in the IDE to stuck runs, missing artifacts, and login errors.
---

Work through the section that matches where the problem shows up: the IDE, the MCP server, the blackbox engine, or the self-hosted platform. If nothing here helps, open an issue with logs at [github.com/suiflex/suitest/issues](https://github.com/suiflex/suitest/issues).

## MCP server

### The server does not appear in my IDE

1. **Restart the IDE (or its MCP connection).** Most IDEs cache the tool list per session; a freshly installed server often stays invisible until you restart.
2. **Check the config entry exists.** For Claude Code that is `./.mcp.json` (project scope) or `~/.claude.json`; for Cursor `~/.cursor/mcp.json`. `npx -y @suiflex/suitest-mcp doctor` inspects every known client's config target and tells you which ones have a Suitest entry.
3. **Check the runtimes.** The launcher needs Node.js >= 18; the server itself needs Python >= 3.11 on `PATH`. Run `node --version` and `python3 --version`.
4. **Test the handshake by hand:**

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n' | npx -y @suiflex/suitest-mcp
```

You should see a `serverInfo` response followed by the tool list. If this works but the IDE shows nothing, the problem is the IDE config, not the server.

### Codex shows `Auth: Unsupported`

This is expected for Suitest. Codex uses the `Auth` column for authentication
handled by remote HTTP/OAuth MCP transports; Suitest runs locally over stdio
and receives `SUITEST_API_KEY` through its process environment. If the Suitest
row is `enabled` and its tools are listed, the connection is working. Use
`codex mcp get suitest` to confirm the transport, command, and masked env names.

Claude Code can show a project-scoped server as `Pending approval` until you
approve the project's `.mcp.json`. Antigravity needs a refresh from Settings,
Customizations after its `mcp_config.json` changes. Neither state indicates a
Suitest protocol error.

### "needs Python >= 3.11" or "failed to start python"

The npm package is only a launcher; the server is bundled Python. Install Python 3.11+ or point the launcher at a specific interpreter:

```bash
SUITEST_PYTHON=/usr/local/bin/python3.12 npx -y @suiflex/suitest-mcp
```

On systems where `python` resolves to Python 2 or an old 3.x, setting `SUITEST_PYTHON` explicitly is the reliable fix.

### The server exits immediately with a credentials error

The server verifies `SUITEST_API_URL` and `SUITEST_API_KEY` at startup by calling `GET /api/v1/api-keys/whoami`, and refuses to start when they are missing, rejected (HTTP error), or the URL is unreachable. Set both in the `env` block of the MCP entry, and check the key in the web UI (Settings, API keys). See [Environment variables](/docs/reference/environment/).

### Results do not show up in the web UI

- Publishing needs `SUITEST_API_URL` and `SUITEST_API_KEY` in the MCP server's environment. The blackbox run stage publishes automatically when they are set and fails loudly when publishing fails.
- Check you are looking at the right **project**: with no configured project id, blackbox publishing creates or reuses a project named after the target host (for example `myapp-example-com`).
- A stale `publish.projectId` fails the publish on purpose (nothing is inserted). Fix the id, or re-run with the explicit `recreate_project` opt-in. See the [MCP tool reference](/docs/reference/mcp-tools/).

### "no active LLM configured for this workspace" (409)

PRD-driven planning and LLM codegen go through the server's LLM proxy, which needs an **Active** provider in Settings, LLM for the workspace your API key belongs to. Removing the provider silently degrades every LLM feature to the deterministic baseline. See [LLM setup](/docs/guides/llm-setup/).

## Blackbox engine

### "discovered 0 route(s)" or "target unreachable: Timeout"

The target must answer within 20 seconds, from the machine that runs the MCP server. Check VPNs, and remember that `localhost` inside a container is not your host machine.

### Only a few routes found on an SPA

The crawler follows `<a href>` links. Routes reachable only through JavaScript `navigate()` calls are not discovered; add them explicitly to `ui.crawl.include` in `suitest.config.json`. See [Configuration](/docs/reference/configuration/).

### Login not detected

Detection is heuristic (a password field, a username-ish input, a submit control). For unusual forms, pin the locators in the config:

```json
"selectors": {
  "loginUsername": "#user",
  "loginPassword": "#pass",
  "loginSubmit": "button.login"
}
```

## Platform (Docker Compose)

### Web loads but login returns 500

The web proxy cannot reach the API, or the API cannot reach the database. Check `docker compose ps` (is `api` up?) and `docker compose logs api --tail 50`. A message like `role "suitest" does not exist` means `SUITEST_DATABASE_URL` points at the wrong Postgres.

### API hangs at startup

Usually a stuck Postgres lock left by a killed client. Inspect `pg_stat_activity` and terminate `idle in transaction` sessions older than a few minutes.

### A run stays QUEUED forever

Runs are executed by the `runner` service, not the API. When a run never leaves QUEUED:

1. `docker compose ps`: is the `runner` container running?
2. `docker compose logs runner --tail 50`: look for Redis connection errors; the worker and the API must point at the same `SUITEST_REDIS_URL`.
3. Check concurrency saturation: `SUITEST_RUNNER_CONCURRENCY` (default 4) caps parallel jobs, and `SUITEST_MCP_MAX_SESSIONS_PER_WORKSPACE` caps MCP sessions per workspace. Long-running runs can queue everything behind them.

### The runner cannot reach my app

The runner executes inside its own container, so a test target configured as `http://localhost:3000` points at the runner container itself, not your machine. Use a hostname the runner can resolve: the compose service name for services in the same stack, or `host.docker.internal` for an app running on the host.

### Videos or screenshots are missing on the run detail page

Artifact upload needs working object storage credentials (`SUITEST_S3_*` in `.env`). Artifacts upload through the API; MCP clients never need S3 credentials themselves. Check `docker compose logs api` for upload errors and confirm MinIO (or your S3) is reachable. See [Evidence](/docs/concepts/evidence/).

### Publish timeouts on large videos

Multi-megabyte videos to remote object storage can exceed default HTTP timeouts. The SDK allows 180 seconds for publishing; if you still hit the limit, investigate MinIO/S3 latency.

## Auth

- **Cannot log in on a fresh install.** Set `SUITEST_SUPERADMIN_EMAIL` and `SUITEST_SUPERADMIN_PASSWORD` in `.env` before first startup; the account is created idempotently when no users exist. Onboarding is invite-only after that (Settings, invite by link).
- **401 from the REST API.** The bearer token is missing or expired, or the API key was revoked. Verify a key with `GET /api/v1/api-keys/whoami`. See the [API reference](/docs/reference/api/).
- **Session lost behind HTTPS.** Set `SUITEST_COOKIE_SECURE=true` when serving over TLS.

## Where logs live

| What | Where |
|---|---|
| API / runner / web service logs | `docker compose logs <service>` (e.g. `api`, `runner`, `web`) |
| Live run status and step logs | Run detail page in the web UI (WebSocket), or `GET /api/v1/runs/{run_id}/logs` |
| Lifecycle and blackbox output | `suitest-output/` next to your `suitest.config.json` (reports, discovery JSON, evidence) |
| MCP server diagnostics | stderr of the MCP process; most IDEs surface it in their MCP/output panel |

:::tip
`apps/api/tests` truncates the database it points at. Never aim `SUITEST_DATABASE_URL` at data you care about when running the test suite locally.
:::
