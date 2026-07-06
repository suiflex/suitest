---
title: Install the MCP server
description: Run the Suitest MCP server with npx and wire it into Claude Code, Cursor, or Windsurf in one command.
---

The Suitest MCP server turns your IDE agent into a QA engineer: it analyzes a
project, generates runnable tests, executes them with evidence, and can publish
results to a Suitest server. It runs from a single `npx` command, so there is
nothing to install permanently.

## Requirements

- Node.js 18 or newer (runs the launcher)
- Python 3.11 or newer on `PATH` (runs the server itself; stdlib only, nothing
  to pip install). Override the interpreter with `SUITEST_PYTHON=/path/to/python`.
- Frontend test execution provisions Playwright and Chromium on demand inside
  the target project. Nothing is installed globally.

## Run the server

```bash
npx -y @suiflex/suitest-mcp
```

This starts a stdio MCP server. Your IDE launches it for you once it is in the
MCP config, so you rarely run this by hand. `npx @suiflex/suitest-mcp mcp` is
the same command with an explicit subcommand.

Prefer a Python-native route? The same server ships on PyPI:

```bash
uvx --from suiflex-suitest-lifecycle suitest-mcp
```

## Zero-config setup: `init`

The fastest way to wire everything up is `init`. Run it in the root of the
project you want to test:

```bash
npx -y @suiflex/suitest-mcp init
```

`init` does four things:

1. **Detects your IDE.** It looks for project markers: `.mcp.json` or a
   `.claude/` directory means Claude Code, a `.cursor/` directory means Cursor.
   Windsurf keeps its MCP config in your home directory, so it has no project
   marker: select it explicitly with `--ide windsurf`.
2. **Detects your app framework.** Next.js, Vite, and Express are read from
   `package.json` dependencies; a `manage.py` file means Django. Detection
   seeds the test mode (`frontend` or `backend`) and the app `baseUrl`. If
   nothing is detected, `init` asks for a base URL (default
   `http://localhost:3000`).
3. **Writes `suitest.config.json`** in the project root, unless one already
   exists. An existing config is never overwritten.
4. **Merges the `suitest` entry into your IDE's MCP config.** The write is
   merge-safe: your other MCP servers are preserved, and a `.bak` backup of the
   config file is created before writing.

When it finishes, restart your IDE and tell the agent: "test my app".

### Flags

| Flag | Values | Purpose |
|------|--------|---------|
| `--ide` | `claude-code`, `cursor`, `windsurf` | Skip IDE detection |
| `--mode` | `local`, `server` | Skip the local/server prompt |
| `--base-url` | URL | App base URL when the framework cannot be auto-detected |
| `--api-url` | URL | Suitest server API URL (server mode, default `http://localhost:4000`) |
| `--api-key` | `sk_suitest_...` | Suitest server API key (server mode) |
| `--yes`, `-y` | | Accept detected defaults, never prompt (CI and scripts) |

### Local vs server mode

`init` asks one question: local or server.

- **Local** writes `SUITEST_MODE=local` into the generated MCP entry and asks
  for no credentials. Test cases, runs, and reports stay on disk under
  `suitest-output/` in your project. No Suitest server is required.
- **Server** writes `SUITEST_API_URL` and `SUITEST_API_KEY` into the entry so
  cases, runs, and evidence publish into the web TCM of a
  [self-hosted Suitest server](/docs/install/docker/).

:::note
In server mode an API key is required. With `--yes` (non-interactive), `init`
fails unless you pass `--api-key`. Create keys in the Suitest web UI.
:::

### Non-interactive examples

```bash
# Local mode, Claude Code, no prompts
npx -y @suiflex/suitest-mcp init --ide claude-code --mode local --yes

# Server mode, Cursor, credentials on the command line
npx -y @suiflex/suitest-mcp init --ide cursor --mode server \
  --api-url https://suitest.example.com --api-key sk_suitest_xxx --yes
```

## Save credentials once: `login`

```bash
npx -y @suiflex/suitest-mcp login
```

`login` prompts for the API URL and key and stores them at
`~/.config/suitest/credentials.json` with `chmod 600`. Every subsequent
`install` reuses them, so you never paste the key twice. `login` needs a TTY;
in scripts, pass `--api-url` and `--api-key` to `install` instead.

## Install into a specific client: `install`

`init` covers Claude Code, Cursor, and Windsurf. `install` supports a wider
client list and gives you finer control:

```bash
npx -y @suiflex/suitest-mcp install                      # interactive picker (TTY)
npx -y @suiflex/suitest-mcp install --client claude-code # target one client directly
```

| `--client` | Writes or delegates to |
|------------|------------------------|
| `claude-code` | `~/.claude.json` (`--scope project` writes `./.mcp.json`) |
| `claude-desktop` | `claude_desktop_config.json` in the Claude support dir |
| `cursor` | `~/.cursor/mcp.json` |
| `windsurf` | `~/.codeium/windsurf/mcp_config.json` |
| `codex` | delegates to `codex mcp add` |
| `gemini-cli` | delegates to `gemini mcp add` |
| `vscode` | delegates to `code --add-mcp` (GitHub Copilot in VS Code) |
| `copilot-cli` | `~/.copilot/mcp-config.json` |
| `opencode` | `opencode.jsonc` |
| `antigravity` | `~/.gemini/antigravity/mcp_config.json` |
| `antigravity-cli` | `~/.gemini/config/mcp_config.json` |
| `generic-json` | prints a portable snippet, writes nothing |

Flags: `--client`, `--name` (entry name, default `suitest`), `--scope
global|project` (Claude Code only), `--api-url` / `--api-key` (skip the saved
credentials), `--print` (show the JSON that will be written), `--dry-run`
(preview without writing), `--force` (overwrite an existing entry).

File-target clients are merged in place with a `.bak` backup. If an entry named
`suitest` already exists with different contents, `install` refuses unless you
pass `--force`.

## Check your setup: `doctor`

```bash
npx -y @suiflex/suitest-mcp doctor
```

`doctor` reports whether Python 3.11+ is on `PATH`, whether saved credentials
exist, and the config target for every supported client (file exists, file
will be created, or CLI missing). Limit it to one client with
`--client <target>`.

## Per-IDE setup

### Claude Code

`init` writes the project-scoped `./.mcp.json`. To wire it manually, add this
to `.mcp.json` in your project root (or `~/.claude.json` for a global entry):

```json
{
  "mcpServers": {
    "suitest": {
      "command": "npx",
      "args": ["-y", "@suiflex/suitest-mcp"],
      "env": {
        "SUITEST_API_URL": "http://localhost:4000",
        "SUITEST_API_KEY": "sk_suitest_xxx"
      }
    }
  }
}
```

For local mode, replace the `env` block with `{ "SUITEST_MODE": "local" }`.

### Cursor

`init` writes the project-scoped `./.cursor/mcp.json`; `install --client
cursor` writes the global `~/.cursor/mcp.json`. Manual config:

```json
{
  "mcpServers": {
    "suitest": {
      "command": "npx",
      "args": ["-y", "@suiflex/suitest-mcp"],
      "env": { "SUITEST_MODE": "local" }
    }
  }
}
```

### Windsurf

Windsurf stores MCP config in your home directory, so auto-detection cannot
find it. Select it explicitly:

```bash
npx -y @suiflex/suitest-mcp init --ide windsurf
```

This writes `~/.codeium/windsurf/mcp_config.json`. Manual config uses the same
shape:

```json
{
  "mcpServers": {
    "suitest": {
      "command": "npx",
      "args": ["-y", "@suiflex/suitest-mcp"],
      "env": {
        "SUITEST_API_URL": "http://localhost:4000",
        "SUITEST_API_KEY": "sk_suitest_xxx"
      }
    }
  }
}
```

## Environment variables

| Variable | Purpose |
|----------|---------|
| `SUITEST_MODE` | `local` keeps all results on disk under `suitest-output/` |
| `SUITEST_API_URL` | Suitest server API URL (server mode) |
| `SUITEST_API_KEY` | Suitest server API key (server mode) |
| `SUITEST_PYTHON` | Path to a Python 3.11+ interpreter, if not on `PATH` |

`SUITEST_API_URL` and `SUITEST_API_KEY` are optional. Without them the tools
still work and results stay local; with them, cases, runs, and evidence land in
the web TCM.

:::tip
There is also a `ci` subcommand (`npx -y @suiflex/suitest-mcp ci`) that runs
the full lifecycle in CI, comments on the pull request, and exits with a
merge-gate code. See [CI with GitHub Actions](/docs/guides/ci-github-action/).
:::

## Next steps

- [Getting started](/docs/guides/getting-started/): the 10-minute path
- [Tutorial: your first run](/docs/guides/tutorial/): a full worked example
- [MCP tools reference](/docs/reference/mcp-tools/): every tool the agent gets
- [Install the full platform with Docker](/docs/install/docker/)
