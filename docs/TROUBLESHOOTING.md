# Troubleshooting

> ✅ Maintained for the current `main`. Covers the MCP server (`npx @suiflex/suitest-mcp` /
> `uvx`), the blackbox engine, and the self-hosted platform.

## MCP server

**`npx -y @suiflex/suitest-mcp` exits: "needs Python >= 3.11"**
The npm package is a launcher; the server is bundled Python (stdlib-only).
Install Python ≥ 3.11 or point the launcher at one:
`SUITEST_PYTHON=/usr/local/bin/python3.12 npx -y @suiflex/suitest-mcp`.

**Server starts but the agent sees no tools**
Verify the handshake by hand:

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n' | npx -y @suiflex/suitest-mcp
```

Expect a `serverInfo` response and a 21-tool list. If your IDE still shows
nothing, restart the MCP connection — most IDEs cache the tool list per session.

**Results don't appear in the Suitest web UI**
Publishing needs `SUITEST_API_URL` + `SUITEST_API_KEY` in the MCP server's
`env` (see `.mcp.json` example in the README). The blackbox run stage publishes
automatically when they're set and **fails loudly** when publishing fails — if
the run passed silently, the env vars are missing. Also check you're looking at
the right **project** in the web sidebar: blackbox auto-creates a project named
after the target host (e.g. `myapp-example-com`).

**`no active LLM configured for this workspace` (409)**
PRD-driven planning and LLM codegen route through the server's `/llm/complete`
proxy. Configure a provider in `Settings → LLM` (it must show **Active**) —
clicking *Remove* deactivates it and every LLM feature silently degrades to the
deterministic baseline.

## Blackbox engine

**`discovered 0 route(s)` / `target unreachable: Timeout`**
Navigation uses `domcontentloaded` + a short settle, but the target must answer
within 20s. Check the URL is reachable from the machine running the MCP server
(VPN, localhost vs. container networking).

**Only a few routes discovered on an SPA**
The crawler follows `<a href="/...">` links. Routes reachable only through
JS `navigate()` calls (buttons with onClick routing) are not discovered yet —
add them to `ui.crawl.include` in `suitest.config.json`.

**Login not detected**
Detection is heuristic (password field + username-ish input + submit). If your
form is unusual, pin the locators:

```json
"selectors": { "loginUsername": "#user", "loginPassword": "#pass", "loginSubmit": "button.login" }
```

**Tests click something destructive**
They shouldn't: safeMode (default ON) blocks delete/logout/billing/payment-style
controls and never submits filled forms unless `testGeneration.allowMutation`
is true. If a control slipped through, please open an issue with the DOM
snippet — the deny-list lives in `blackbox/detector.py`.

## Platform (Docker Compose)

**Web loads but login returns 500**
The vite/nginx proxy can't reach the API. `docker compose ps` — is `api` up?
`docker compose logs api --tail 50` usually shows a DB connection error
(`role "suitest" does not exist` → your `SUITEST_DATABASE_URL` points at the
wrong Postgres).

**API hangs at startup**
Usually a stuck Postgres lock from a killed client. Inspect
`pg_stat_activity`; terminate `idle in transaction` sessions older than a few
minutes.

**Videos/screenshots missing on run detail**
The API needs object storage credentials (`SUITEST_S3_*` in `.env`). Artifacts
upload **through the API** — the MCP client never needs S3 credentials.

**Publish timeout from the lifecycle**
Multi-MB videos to remote object storage can exceed default HTTP timeouts; the
SDK ships with 180s for publish. If you still hit it, check MinIO/S3 latency.

## CI

**`pytest` wipes my data**
`apps/api/tests` resets the database it points at (TRUNCATE) — never aim
`SUITEST_DATABASE_URL` at a database whose data you care about. CI uses
disposable Postgres/Redis services; do the same locally.

Still stuck? Open an issue with logs:
<https://github.com/suiflex/suitest/issues>
