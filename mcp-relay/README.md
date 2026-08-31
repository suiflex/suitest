# Suitest over Streamable HTTP (MCP relay)

Suitest's own MCP server — `@suiflex/suitest-mcp` — speaks **only stdio** (its
lifecycle server is a minimal NDJSON-over-pipes JSON-RPC process; see
`packages/lifecycle/src/suitest_lifecycle/mcp_server.py`). That limits clients
to boxes that can spawn the npm package locally.

This directory ships a thin relay that exposes the same tools over the
[Streamable HTTP](https://modelcontextprotocol.io) transport, so any MCP client
can drive Suitest over HTTPS from anywhere.

```
MCP client ──HTTPS──▶ Caddy ──▶ mcp-relay (mcp-proxy, :4044) ──stdio──▶ suitest-mcp
                                                                              │
                                                                    http://api:4000
```

## How it works

- [`mcp-proxy`](https://github.com/sparfenyuk/mcp-proxy) (npm) listens on
  `/mcp` and translates Streamable-HTTP JSON-RPC into stdio frames.
- The spawned child is the global `suitest-mcp` binary from
  `@suiflex/suitest-mcp`; it inherits the relay's environment, so compose sets
  `SUITEST_API_URL` / `SUITEST_API_KEY` and they reach Suitest's API.
- Clients authenticate with `X-API-Key: <MCP_RELAY_TOKEN>` (configured on the
  proxy via `--apiKey`). Combined with a Suitest API key, that's the remote
  access boundary.

## Files

| Path | Purpose |
|------|---------|
| `Dockerfile` | `node:22-bookworm-slim` + `python3` (Suitest needs ≥3.11) + `mcp-proxy` + `@suiflex/suitest-mcp` |
| `../compose.deploy.yml` | `mcp-relay` service wiring it into the stack |

## Structured config for an MCP client

```json
{
  "mcpServers": {
    "suitest": {
      "type": "streamable-http",
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "X-API-Key": "<MCP_RELAY_TOKEN>"
      }
    }
  }
}
```

> Stanza shape varies by client; `type: "streamable-http"` / `"http"` is the
> commonly accepted marker. The token and the Suitest API key are independent.

## Notes / limits

- **One stdio server per proxy process.** Stateful Streamable-HTTP keeps a
  session open vs. Suitest's pooled runner (idle TTL 60s), so each connected
  client holds a spawned `suitest-mcp`. Reconfigure pooling
  (`SUITEST_MCP_MAX_SESSIONS_PER_WORKSPACE`) if you need many concurrent
  remote agents.
- `mcp-proxy --streamEndpoint` defaults to `/mcp`.
- The underlying server is MCP 2024-11-05; keep `mcp-proxy`'s default legacy
  upstream protocol.
