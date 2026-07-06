---
title: Local bundle (one command)
description: Run the full Suitest platform on your laptop with one command — web dashboard, SQLite, and MCP wiring. No Docker, no cloud services, no LLM key.
---

`@suiflex/suitest` boots the entire platform locally: the web dashboard, an
API on SQLite, a run supervisor, and your IDE's MCP config — wired together
by a single command. No Docker, no Postgres, no S3, no LLM API key (test
generation uses MCP sampling through your IDE agent).

```bash
npx @suiflex/suitest onboard
```

This is the recommended route for a solo developer who wants the dashboard.
If you only need agent-generated tests without a UI, the
[MCP server alone](/docs/install/mcp-server/) is lighter. For a team server
with Postgres and object storage, use
[Docker Compose](/docs/install/docker/) or [Helm](/docs/install/kubernetes/).

## Requirements

- Node.js 18 or newer
- [`uv`](https://docs.astral.sh/uv/) — provisions Python 3.12 and the
  per-project virtualenv on demand. If it's missing, `onboard` prints the
  install one-liner and exits.

Everything else ships inside the npm package (~3 MB: prebuilt dashboard +
Suitest wheels). The first run needs the network only for Python dependencies
from PyPI; after that the stack starts offline.

## What `onboard` does

Run it in the root of the project you want to test:

```bash
npx @suiflex/suitest onboard
```

1. **Provisions the runtime** — creates `.suitest/.venv` with Python 3.12 via
   `uv` and installs the bundled Suitest wheels into it.
2. **Bootstraps the database** — creates a SQLite schema at
   `.suitest/suitest.db`.
3. **Boots the stack** — the API + web dashboard on `http://127.0.0.1:4000`
   (falls back to 4001–4009 if the port is taken) and a supervisor that
   executes queued runs. Both bind to `127.0.0.1` only.
4. **Mints a local API key** — a superadmin account is created with generated
   credentials, stored in `.suitest/credentials.json` (mode `600`).
5. **Wires your IDE** — writes `suitest.config.json` and merges a `suitest`
   entry into your IDE's MCP config (Claude Code, Cursor, or Windsurf),
   pointed at the local API with the minted key.

Then restart your IDE, start your app, and prompt the agent:

> Test my app at http://localhost:3000

Generated cases, runs, and evidence (video, screenshots, HAR, DOM) appear in
the dashboard as the agent works.

## Commands

| Command | What it does |
|---------|--------------|
| `suitest onboard` | full setup + boot + IDE wiring (idempotent) |
| `suitest up` | boot the local stack (reuses everything already provisioned) |
| `suitest down` | stop the stack |
| `suitest init` | wire the MCP config only, without booting |

Useful flags: `--port <n>` (preferred dashboard port),
`--ide <claude-code|cursor|windsurf>` (skip IDE detection).

## Where the data lives

Everything is per-project, under `./.suitest/`:

```
.suitest/
├── suitest.db          # SQLite database (cases, runs, results)
├── artifacts/          # run evidence: video, screenshots, HAR, DOM
├── logs/               # api.log, supervisor.log
├── .venv/              # Python runtime (uv-managed)
├── credentials.json    # local superadmin + API key (chmod 600)
└── pids.json           # running process ids + port
```

Delete the directory to reset the project completely.

## Troubleshooting

- **Dashboard doesn't come up** — check `.suitest/logs/api.log`. The stack
  refuses to start twice: `suitest up` prints `Already running` with the URL.
- **`uv` not found** — install it, then re-run:
  `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Port busy** — `onboard`/`up` walk up from 4000 automatically; pass
  `--port` to choose your own.
- **IDE not detected** — the stack still boots; wire the config later with
  `suitest init --ide <claude-code|cursor|windsurf>`.

## Monorepo development

Working on Suitest itself? Build the assets and point the launcher at them
instead of the bundled copies:

```bash
scripts/build-bundle-assets.sh
SUITEST_BUNDLE_WEB_DIST=$PWD/dist/bundle/web \
SUITEST_BUNDLE_WHEELS_DIR=$PWD/dist/bundle/wheels \
node packages/suitest-npx/bin/suitest.js onboard
```
