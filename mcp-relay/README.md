# mcp-relay — Streamable HTTP front for the Suitest MCP server

Suitest's own MCP server (`@suiflex/suitest-mcp`) speaks **stdio only**. This
image wraps it behind [mcp-proxy](https://github.com/sparfenyuk/mcp-proxy),
which exposes the same tools over the Streamable HTTP transport at `/mcp` —
the deployment-facing documentation lives in
[`docs/DEPLOYMENT.md` § 1.5](../docs/DEPLOYMENT.md) (reverse proxy & remote
MCP access) and the acceptance criterion in
[`docs/ROADMAP.md` M4-33](../docs/ROADMAP.md).

```
MCP client ──HTTPS──▶ reverse proxy ──▶ mcp-relay (:4044) ──stdio──▶ suitest-mcp
                                                            │
                                                  http://api:4000
```

## Layout

| Path | Purpose |
|------|---------|
| `Dockerfile` | `node:22-bookworm-slim` + `python3` (Suitest needs ≥3.11 on PATH) + `mcp-proxy` + `@suiflex/suitest-mcp` |
| `../compose.deploy.yml` | the `mcp-relay` service wiring it into the deploy stack |

## How it works

- `mcp-proxy` (npm) listens on `:4044`, serves `/mcp` (Streamable HTTP,
  protocol 2024-11-05 upstream), and translates JSON-RPC HTTP ↔ stdio frames.
- The spawned child is the globally installed `suitest-mcp` binary; it
  **inherits the relay's environment**, so compose-supplied
  `SUITEST_API_URL` / `SUITEST_API_KEY` reach the Suitest API.
- Clients authenticate with `X-API-Key: $MCP_RELAY_TOKEN` (`--apiKey`). This
  relay token is **independent** of the Suitest API key: the first gates
  clients → relay, the second gates relay → Suitest API.
- `SUITEST_API_KEY` and `MCP_RELAY_TOKEN` are required (`${VAR:?}` in compose);
  the relay refuses to boot half-configured.

## Operational notes

- **One stdio child per connected client.** Stateful Streamable-HTTP sessions
  keep the child alive for the session TTL, so N concurrent remote agents ≈ N
  `suitest-mcp` processes.
- `mcp-proxy --streamEndpoint` defaults to `/mcp`.
- The `CMD` uses shell form so the container shell expands
  `${MCP_RELAY_TOKEN}` from its environment at runtime (an exec-form CMD would
  pass the literal string through).
