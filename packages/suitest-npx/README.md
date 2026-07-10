# @suiflex/suitest

One command runs the full Suitest stack locally — web dashboard + SQLite +
MCP — no Docker, no cloud services, no LLM API key (MCP sampling).

## Install

```bash
# with Node >= 18
npm i -g @suiflex/suitest && suitest onboard

# or try without installing
npx @suiflex/suitest onboard
```

Requires [`uv`](https://docs.astral.sh/uv/) (provisions Python 3.12 on
demand); `onboard` prints the install one-liner when it's missing.

## Commands

| Command | What it does |
|---------|--------------|
| `suitest onboard` | provision runtime (per-project uv venv from bundled wheels), boot the stack, mint a local API key, wire your IDE's MCP config |
| `suitest up` | boot the local stack (idempotent) |
| `suitest down` | stop it |
| `suitest status` | is the stack running? (URL, version, health) |
| `suitest settings` | terminal panel: generate/refresh the API key + show config, no browser |
| `suitest init` | wire MCP config only |

Data lives in `./.suitest/` (SQLite DB, artifacts, logs, venv, credentials).
The API binds to `127.0.0.1` only. The web dashboard and Suitest wheels ship
inside this package (~3 MB); first run needs the network only for PyPI
dependencies, later runs are offline.

Dev override (use a local asset build instead of the bundled one):
`SUITEST_BUNDLE_WEB_DIST`, `SUITEST_BUNDLE_WHEELS_DIR` — produced by
`scripts/build-bundle-assets.sh` at the repo root.

This package is a launcher. The MCP server itself is `@suiflex/suitest-mcp`
(unchanged, also used for Docker/server installs).
