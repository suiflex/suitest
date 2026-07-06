# @suiflex/suitest

One command runs the full Suitest stack locally — web dashboard + SQLite +
MCP — no Docker, no cloud services, no LLM API key (MCP sampling).

## Install

```bash
# one-liner (provisions Node + uv)
curl -fsSL https://raw.githubusercontent.com/suiflex/suitest/main/scripts/install.sh | bash

# or, with Node >= 18 already installed
npm i -g @suiflex/suitest && suitest onboard

# or try without installing
npx @suiflex/suitest onboard
```

## Commands

| Command | What it does |
|---------|--------------|
| `suitest onboard` | provision runtime (uv venv + release assets), boot the stack, mint a local API key, wire your IDE's MCP config |
| `suitest up` | boot the local stack (idempotent) |
| `suitest down` | stop it |
| `suitest init` | wire MCP config only |

Data lives in `./.suitest/` (SQLite DB, artifacts, logs, venv, credentials).
The API binds to `127.0.0.1` only. First run downloads pinned assets from
GitHub Releases (`bundle-v<version>`); later runs are offline.

Dev override (skip downloads): `SUITEST_BUNDLE_WEB_DIST`, `SUITEST_BUNDLE_WHEELS_DIR`,
`SUITEST_BUNDLE_BASE_URL`.

This package is a launcher. The MCP server itself is `@suiflex/suitest-mcp`
(unchanged, also used for Docker/server installs).
