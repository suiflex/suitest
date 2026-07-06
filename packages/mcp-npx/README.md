# @suiflex/suitest-mcp

Run the [Suitest](https://github.com/suiflex/suitest) MCP server with a single command:

```bash
npx -y @suiflex/suitest-mcp
```

Suitest turns your IDE agent (Claude Code, Cursor, Codex — anything that speaks
[MCP](https://modelcontextprotocol.io)) into a QA automation engineer: analyze a
project, generate runnable tests, execute them with evidence (video, per-step
screenshots), and publish results to a Suitest server.

It includes a **blackbox DOM testing engine** — test any web app with no repo
access at all: a URL, test credentials, and a scope are enough. Deterministic,
no LLM key required.

## Quickstart

```bash
npx -y @suiflex/suitest-mcp init
```

One command: detects your IDE (Claude Code, Cursor, Windsurf) and app framework
(Next.js, Vite, Express, Django), asks one thing — local or server — then writes
`suitest.config.json` and merges the Suitest entry into your IDE's MCP config
(your other MCP servers are preserved). **Local mode needs no API key.**

Then restart your IDE and tell the agent: **"test my app"**.

Want the full platform (web dashboard included) on your laptop too?
`npx @suiflex/suitest onboard` boots it in one command and wires the same MCP
config for you — see [`@suiflex/suitest`](https://www.npmjs.com/package/@suiflex/suitest).
This package is the MCP-server-only route.

Non-interactive (CI / scripts):

```bash
npx -y @suiflex/suitest-mcp init --ide claude-code --mode local --yes
npx -y @suiflex/suitest-mcp init --ide cursor --mode server \
  --api-url https://suitest.example.com --api-key sk_suitest_… --yes
```

Flags: `--ide claude-code|cursor|windsurf`, `--mode local|server`, `--base-url`
(app URL when the framework can't be auto-detected), `--api-url` / `--api-key`
(server mode), `--yes` (accept detected defaults, no prompts).

## Requirements

- Node.js ≥ 18 (to run this launcher)
- Python ≥ 3.11 on `PATH` (the server itself; stdlib-only, nothing to install).
  Override the interpreter with `SUITEST_PYTHON=/path/to/python`.
- Frontend test execution provisions Playwright/Chromium on demand.

## IDE setup

Fastest path — let the installer write the config for you:

```bash
npx -y @suiflex/suitest-mcp login                        # save API URL + key once (TTY)
npx -y @suiflex/suitest-mcp install                      # pick a client (arrow keys + type to filter)
npx -y @suiflex/suitest-mcp install --client claude-code # or target one directly
npx -y @suiflex/suitest-mcp doctor                       # inspect every client's config target
```

`login` stores the credentials at `~/.config/suitest/credentials.json` (chmod
600) and every `install` reuses them, writing the right `env` block into the
chosen client. Supported targets:

| `--client`        | Writes / delegates to |
|-------------------|-----------------------|
| `claude-code`     | `~/.claude.json` (`--scope project` → `./.mcp.json`) |
| `claude-desktop`  | `claude_desktop_config.json` in the Claude support dir |
| `cursor`          | `~/.cursor/mcp.json` |
| `codex`           | delegates to `codex mcp add` |
| `gemini-cli`      | delegates to `gemini mcp add` |
| `vscode`          | delegates to `code --add-mcp` (GitHub Copilot in VS Code) |
| `copilot-cli`     | `~/.copilot/mcp-config.json` |
| `opencode`        | `opencode.jsonc` |
| `antigravity`     | `~/.gemini/antigravity/mcp_config.json` |
| `antigravity-cli` | `~/.gemini/config/mcp_config.json` |
| `generic-json`    | prints a portable snippet, writes nothing |

Flags: `--name` (entry name, default `suitest`), `--api-url` / `--api-key`
(skip the saved creds), `--print`, `--dry-run`, `--force`.

Prefer to wire it by hand? Add to your project's `.mcp.json` (Claude Code) or
the equivalent MCP config:

```json
{
  "mcpServers": {
    "suitest": {
      "command": "npx",
      "args": ["-y", "@suiflex/suitest-mcp"],
      "env": {
        "SUITEST_API_URL": "http://localhost:4000",
        "SUITEST_API_KEY": "sk_suitest_…"
      }
    }
  }
}
```

`SUITEST_API_URL`/`SUITEST_API_KEY` connect the pipeline to a self-hosted
Suitest server so cases, runs, and evidence land in the web TCM (and unlock
LLM-assisted generation through the server's `/llm/complete` proxy). Without
them the tools still work — results stay local under `suitest-output/`.

## What the agent gets

22 tools, three workflows:

| Workflow | Tools | Needs |
|---|---|---|
| Repo-based lifecycle | `analyze_project`, `generate_test_cases`, `run_tests`, `generate_report`, … | a checkout + `suitest.config.json` |
| Blackbox (no repo) | `bootstrap_project` (browser setup wizard), `blackbox_discover_app`, `blackbox_generate_playwright_tests`, `blackbox_run_playwright_tests`, `blackbox_summarize_findings`, … | a URL + credentials |
| PRD-driven | `blackbox_generate_playwright_tests` with `prd_file` (markdown) | a PRD + a workspace LLM |

Full tool reference: [docs/MCP_PLUGINS.md](https://github.com/suiflex/suitest/blob/main/docs/MCP_PLUGINS.md)
and [docs/BLACKBOX_UI_TESTING.md](https://github.com/suiflex/suitest/blob/main/docs/BLACKBOX_UI_TESTING.md).

## CLI

```bash
npx -y @suiflex/suitest-mcp --help      # usage + config snippet
npx -y @suiflex/suitest-mcp --version
```

## How it works

This package bundles the `suitest_lifecycle` Python module (stdlib-only) and a
thin Node launcher that starts it as a stdio MCP server. No pip install, no
virtualenv, no daemon.

## License

Apache-2.0 — see [LICENSE](./LICENSE).
