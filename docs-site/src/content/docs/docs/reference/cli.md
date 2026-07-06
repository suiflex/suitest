---
title: CLI reference
description: All three Suitest command-line surfaces, the npx MCP launcher, the Python lifecycle CLI, and the platform CLI, with every flag.
---

Suitest ships three command-line surfaces. They serve different jobs:

| Surface | Invocation | Job |
|---|---|---|
| npx launcher | `npx -y @suiflex/suitest-mcp` | Start the MCP server, onboard an IDE, run CI |
| Lifecycle CLI | `suitest` (from `suiflex-suitest-lifecycle`) | Zero-tier blackbox runs and the config-driven lifecycle, local |
| Platform CLI | `suitest` (from the `cli/` package) | Talk to a running Suitest server: trigger runs, list cases and MCP providers |

:::caution
Both Python packages register a `suitest` console script. Whichever package is installed in the active environment wins. To be explicit, use `python -m suitest_lifecycle.cli` for the lifecycle CLI and `python -m suitest_cli.main` for the platform CLI.
:::

## npx @suiflex/suitest-mcp

The npm launcher. Requires Node.js >= 18 and Python >= 3.11 on `PATH` (override the interpreter with `SUITEST_PYTHON=/path/to/python`). The MCP server itself is bundled, stdlib-only Python; nothing is pip-installed.

```bash
npx -y @suiflex/suitest-mcp                    # start the stdio MCP server (default)
npx -y @suiflex/suitest-mcp mcp                # same, explicit subcommand
npx -y @suiflex/suitest-mcp init               # zero-config onboarding (detect IDE + framework)
npx -y @suiflex/suitest-mcp install            # interactive client picker (TTY)
npx -y @suiflex/suitest-mcp login              # save API URL + key once
npx -y @suiflex/suitest-mcp doctor             # check client config targets
npx -y @suiflex/suitest-mcp ci                 # run tests in CI, comment on the PR, exit-code gate
npx -y @suiflex/suitest-mcp --help             # -h works too
npx -y @suiflex/suitest-mcp --version          # -v; bundled server version
```

### `mcp` (default)

Starts the stdio MCP server (`python -m suitest_lifecycle.mcp_server`). This is what your IDE's MCP config should run. See [Install the MCP server](/docs/install/mcp-server/) and the [MCP tool reference](/docs/reference/mcp-tools/).

### `init`

Zero-config onboarding: detects your IDE and app framework, writes `suitest.config.json`, and merges the Suitest entry into the IDE's MCP config (existing MCP servers are preserved).

| Flag | Values | Meaning |
|---|---|---|
| `--ide` | `claude-code` \| `cursor` \| `windsurf` | Target IDE (skip auto-detection) |
| `--mode` | `local` \| `server` | Local mode needs no API key; server mode publishes to a Suitest server |
| `--base-url` | URL | App URL when the framework cannot be auto-detected |
| `--api-url` | URL | Suitest server URL (server mode) |
| `--api-key` | key | Suitest API key (server mode) |
| `--yes`, `-y` | | Accept detected defaults, no prompts (CI / scripts) |

```bash
npx -y @suiflex/suitest-mcp init --ide claude-code --mode local --yes
npx -y @suiflex/suitest-mcp init --ide cursor --mode server \
  --api-url https://suitest.example.com --api-key sk_suitest_... --yes
```

### `install`

Writes (or delegates) the MCP entry for a specific client. With no flags on a TTY it opens an interactive picker.

| Flag | Meaning |
|---|---|
| `--client <target>` | Client to configure (see table below) |
| `--name` | Entry name in the client config (default `suitest`) |
| `--scope global\|project` | For `claude-code`: `project` writes `./.mcp.json` instead of `~/.claude.json` |
| `--api-url` / `--api-key` | Use these credentials instead of the saved ones |
| `--print` | Print the resulting config snippet |
| `--dry-run` | Show what would be written without writing |
| `--force` | Overwrite an existing entry |

Supported `--client` targets: `claude-code`, `claude-desktop`, `cursor`, `windsurf`, `codex` (delegates to `codex mcp add`), `gemini-cli` (delegates to `gemini mcp add`), `vscode` (delegates to `code --add-mcp`), `copilot-cli`, `opencode`, `antigravity`, `antigravity-cli`, and `generic-json` (prints a portable snippet, writes nothing).

### `login`

Prompts for the API URL and key once and stores them at `~/.config/suitest/credentials.json` (mode 600; override the directory with `SUITEST_CONFIG_DIR`). Every subsequent `install` reuses them.

### `doctor`

Inspects every known client's config target and reports whether a Suitest entry is present.

### `ci`

Runs the full lifecycle in CI, renders a PR comment, and exits with a merge-gate code. All arguments after `ci` (including `--help`) are forwarded to `python -m suitest_lifecycle.ci` (Python argparse):

| Flag | Default | Meaning |
|---|---|---|
| `--config` | `suitest.config.json` | Config file to run |
| `--dry-run` | off | Print the markdown comment instead of publishing it (local debugging) |

Exit codes: `0` all tests passed, `1` at least one test failed, `2` infrastructure error (including a missing Python interpreter or packaging problem). When no supported CI forge or token is detected, the comment is printed instead of published and the command does not fail for that reason. See [CI with GitHub Actions](/docs/guides/ci-github-action/).

## Lifecycle CLI (`suitest`, Python)

Installed by the `suiflex-suitest-lifecycle` package (also runnable as `python -m suitest_lifecycle.cli`). Stdlib argparse, no LLM required.

### `suitest zero blackbox` / `suitest zero ui`

Blackbox DOM testing from a URL, no repo needed. `ui` is an alias of `blackbox`. Requires `--url` or `--config`. Runs discover, generate, run, summarize (the run stage publishes automatically when `SUITEST_API_URL` / `SUITEST_API_KEY` are set).

| Flag | Default | Meaning |
|---|---|---|
| `--url` | | Target app URL (e.g. `http://localhost:3000`) |
| `--config` | | `suitest.config.json` with a `ui` section |
| `--username` | | Test credential username/email |
| `--password` | | Test credential password |
| `--max-routes` | `0` | Crawl route cap (config default 30) |
| `--max-depth` | `0` | Crawl depth cap (config default 3) |
| `--headed` | off | Run the browser headed |
| `--record-video` | off | Record video evidence for generated tests |
| `--no-safe-mode` | off | Allow destructive links/actions (default: safeMode ON) |
| `--prd` | | Markdown PRD file, for a PRD-driven plan via the workspace LLM |
| `--discover-only` | off | Stop after discovery + graph (skip test generation/execution) |

:::note
`--url`, `--config`, `--username`, `--password`, `--max-routes`, and `--prd` are applied directly. `--max-depth`, `--headed`, `--record-video`, and `--no-safe-mode` are parsed but currently take effect through the config file's `ui` section (`crawl.maxDepth`, `headed`, `recordVideo`, `crawl.safeMode`); set them there for reliable behavior. See [Configuration](/docs/reference/configuration/).
:::

```bash
suitest zero blackbox --url http://localhost:3000 \
  --username qa@example.com --password password123
suitest zero blackbox --config suitest.config.json --max-routes 30
```

Exit code: `0` when every stage succeeded, `1` otherwise.

### `suitest test`

Runs the full config-driven lifecycle (analyze, generate, start, wait ready, run, report).

| Flag | Default | Meaning |
|---|---|---|
| `--config` | `suitest.config.json` | Config file |
| `--recreate-project` | off | EXPLICITLY recreate the Suitest project when `publish.projectId` is stale and repair finds no match (otherwise a stale binding fails the run) |

Exit code: `0` on success, `1` on failure.

### `suitest mcp`

Serves the stdio MCP server in the current Python environment (same server the npx launcher starts).

## Platform CLI (`suitest`, from `cli/`)

A thin front-end over the `suiflex-suitest-sdk` REST client for a **running Suitest server** (also runnable as `python -m suitest_cli.main`). Exit code is non-zero on API error so it composes in CI pipelines.

### Global flags and environment

| Flag | Env fallback | Default |
|---|---|---|
| `--api-url` | `SUITEST_API_URL` | `http://localhost:4000` |
| `--token` | `SUITEST_TOKEN` | |
| `--workspace` | `SUITEST_WORKSPACE_ID` | |

### `suitest run`

Trigger a run for a selection of cases.

| Flag | Meaning |
|---|---|
| `--project <id>` | Project id (required) |
| `--case <id>` | Case id, repeatable (required) |
| `--branch` | Branch label for the run |
| `--suite` | Suite name (used as the run name when `--name` is absent) |
| `--name` | Run name |
| `--wait` | Block until the run finishes |

```bash
suitest run --project prj_1 --case case_1 --case case_2 --branch main --wait
```

Exit codes: `0` queued (or finished PASSED with `--wait`), `2` when a waited run finishes in any non-PASSED status, `1` on API error.

### `suitest cases list`

| Flag | Default | Meaning |
|---|---|---|
| `--limit` | `50` | Max cases to list |
| `--json` | off | Emit raw JSON instead of a table |

### `suitest mcp ls`

List the server's MCP providers with their status.

| Flag | Meaning |
|---|---|
| `--json` | Emit raw JSON |

### `suitest generate`

Analyze the project and generate test cases locally (no execution, no server needed).

| Flag | Default | Meaning |
|---|---|---|
| `--config` | `suitest.config.json` | Path to the config file |

### `suitest test`

Full local lifecycle: generate, start, wait, run, report.

| Flag | Meaning |
|---|---|
| `--config` | Path to `suitest.config.json` (default `suitest.config.json`) |
| `--json` | Emit a structured JSON result |
| `--no-autostart` | Do not spawn the target; only wait for readiness |
| `--publish` | Publish results into a running Suitest (REST ingest) |
| `--enrich` | Add LLM edge-case enrichment (deterministic mock) |

Exit codes: `0` on success, `2` on a failed lifecycle, `1` on config or API errors.
