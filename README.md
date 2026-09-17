<p align="right"><a href="./README_ID.md">🇮🇩 Bahasa Indonesia</a></p>

# Suitest — A Testing Platform That Works for Everyone

> **Suitest Cloud collaboration is Coming Soon.** The current product is the free,
> self-hosted platform. Every supported model provider unlocks the same features.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/logo-dark.svg">
    <img src="assets/brand/logo-light.svg" alt="Suitest" width="380">
  </picture>
</p>

<p align="center">
  <strong>Manage test cases. Run them automatically. Analyze with AI.<br>Your data stays yours — no subscription fees.</strong>
</p>

<p align="center">
  <a href="https://github.com/suiflex/suitest/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/suiflex/suitest/ci.yml?branch=main&style=for-the-badge" alt="CI status"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-4ade80.svg?style=for-the-badge" alt="Apache-2.0 License"></a>
  <a href="https://modelcontextprotocol.io"><img src="https://img.shields.io/badge/MCP-native-4ade80?style=for-the-badge" alt="MCP native"></a>
</p>

<p align="center">
  <a href="https://www.npmjs.com/package/@suiflex/suitest"><img src="https://img.shields.io/npm/v/%40suiflex%2Fsuitest?style=for-the-badge&label=launcher&color=4ade80" alt="@suiflex/suitest on npm"></a>
  <a href="https://www.npmjs.com/package/@suiflex/suitest-mcp"><img src="https://img.shields.io/npm/v/%40suiflex%2Fsuitest-mcp?style=for-the-badge&label=mcp&color=4ade80" alt="@suiflex/suitest-mcp on npm"></a>
  <a href="https://www.npmjs.com/package/@suiflex/suitest-sdk"><img src="https://img.shields.io/npm/v/%40suiflex%2Fsuitest-sdk?style=for-the-badge&label=sdk%20(ts)&color=4ade80" alt="@suiflex/suitest-sdk on npm"></a>
  <a href="https://pypi.org/project/suiflex-suitest-sdk/"><img src="https://img.shields.io/pypi/v/suiflex-suitest-sdk?style=for-the-badge&label=sdk%20(py)&color=4ade80" alt="suiflex-suitest-sdk on PyPI"></a>
</p>

<p align="center">
  <img src="assets/brand/readme-hero.png" alt="Suitest — QA platform that tests browser, API, and database in one place." width="960">
</p>

---

## What is Suitest?

**Suitest** is a free, self-hostable software testing platform.

**Here's what that means:** You have a website or app. You want to make sure all its features work correctly — buttons are clickable, forms can be filled, data is saved properly. In the old days, you'd use spreadsheets to track test cases and run each one manually. **Suitest replaces all of that with a single application.**

### What can Suitest do?

| What you need | Suitest solution |
|---------------|-----------------|
| 📝 Keep all test cases in one place | ✅ **Test Case Management** — create, edit, organize test cases and suites |
| 🤖 Run tests automatically | ✅ **Automated Runner** — test browser, API, database automatically |
| 📸 Get screenshot & video evidence | ✅ **Evidence Capture** — every test produces screenshots and videos |
| 🐛 Track bugs from failed tests | ✅ **Defect Tracking** — bugs are logged automatically when tests fail |
| 📊 See testing reports | ✅ **Dashboard & Analytics** — pass rate, coverage, readiness at a glance |
| 🔗 Link requirements ↔ tests ↔ bugs | ✅ **Traceability** — every test connects to requirements and bugs |
| 🔌 Integrate with CI/CD | ✅ **Webhooks** — GitHub, GitLab, Jira, Slack |
| 🤖 Use AI to generate tests | ✅ **AI (optional)** — generate tests from PRDs, auto-diagnosis |

### Who uses Suitest?

| Profile | Needs | How Suitest helps |
|---------|-------|-------------------|
| 👩‍💻 **QA Engineer** | Manage test cases, run automatically, track defects | TCM, MCP runner, evidence, defects |
| 👨‍💻 **Developer** | Ensure PRs are safe to merge, cross-cutting tests | CI workflows and mixed-target tests |
| 📋 **Product Manager** | See release readiness before deploy | Readiness, analytics, and traceability |
| 🏦 **IT / Infrastructure** | Self-host for compliance | BYO infrastructure, model, and data |
| 🚀 **Startup / Indie Dev** | Avoid subscriptions and vendor lock-in | Free self-hosted platform with BYO LLM |

---

## Why use Suitest?

### vs TestRail / Zephyr
TestRail is paid ($30/user/month) and has no automated runner. **Suitest combines TCM, an automated runner, and MCP plugins in one free self-hosted platform.**

### vs Playwright (standalone)
Playwright can only test browsers. **Suitest uses Playwright as one of many plugins** + adds TCM layer + traceability + multi-target (not just browsers).

### vs TestSprite
TestSprite has vendor lock-in (their LLM, their cloud). **Suitest: BYO LLM, self-host, universal MCP plugin (test API/DB/Infra/Mobile, not just browsers).**

---

## Get Started in 3 Steps

### ⚡ Step 1: Install (1 minute)

**What you need:**
- [Node.js](https://nodejs.org/) version 18 or higher (download from nodejs.org)
- [uv](https://docs.astral.sh/uv/) — Python package manager (install with: `pip install uv`)

**Check if you have them installed:**

Open a terminal (Command Prompt / PowerShell / Terminal) and type:

```bash
node --version    # must be v18 or higher
uv --version      # must be installed
```

**Install Suitest:**

```bash
npx @suiflex/suitest onboard
```

> 💡 **What is `npx`?** It's part of Node.js that lets you run programs without manual installation. `npx @suiflex/suitest onboard` downloads and runs Suitest automatically.

### ⚡ Step 2: Open the Dashboard (30 seconds)

After installation, Suitest will give you a web address (usually `http://localhost:4000`). Open it in your browser.

**First-time login:**
- Email: the one you entered during onboard
- Password: the one you entered during onboard

> 💡 **Tip:** If you forgot your password, run `suitest settings` in the terminal to regenerate your API key.

### ⚡ Step 3: Create Your First Test Case

1. **Log in** to the dashboard
2. Click **"+ New Project"** → give it a name
3. Click **"+ New Suite"** → give it a name (a collection of test cases)
4. Click **"+ New Case"** → create your first test case
5. Add **steps** — each step has an action (click a button, fill a form, etc.)
6. Open **Settings → LLM**, save a provider, and click **Test connection**
7. Click **"Run"** → the test will run automatically

> 💡 **First time?** Check out the [interactive demo](http://localhost:3000) after running `make demo` — it comes with pre-built test cases ready to go.

---

## Installation Options (Detailed)

### 1. 🏠 Local Install — One Command (Recommended for Beginners)

```bash
npx @suiflex/suitest onboard
```

**What this command does:**

Downloads and installs all required components.

**Managing Suitest after installation:**

| Want to... | Command |
|------------|---------|
| Start Suitest | `suitest up` |
| Stop Suitest | `suitest down` |
| Generate/refresh API key | `suitest settings` |
| Change port | `suitest onboard --port 5000` |

### 2. 🌐 MCP Server Only (No Platform Install)

If you only need the MCP server for IDEs (Claude Code, Cursor, Codex):

```bash
npx -y @suiflex/suitest-mcp
```

> 💡 **What is MCP?** MCP (Model Context Protocol) is a standard that lets AI agents (like Claude Code) run tests. With the MCP server, you can generate tests from your code repo.

**Example configuration for Claude Code / Cursor (`.mcp.json`):**

```json
{
  "mcpServers": {
    "suitest": {
      "command": "npx",
      "args": ["-y", "@suiflex/suitest-mcp"],
      "env": {
        "SUITEST_API_URL": "http://localhost:4000",
        "SUITEST_API_KEY": "sk_suitest_..."
      }
    }
  }
}
```

> 💡 **`SUITEST_API_URL` and `SUITEST_API_KEY` are required.** MCP startup verifies the key and stops until the workspace LLM has been validated in Settings. Provider credentials stay on the Suitest server.

### 3. 🐳 Full Platform — Docker Compose

If you want to run all components (API, web, runner, database, Redis, MinIO):

```bash
git clone https://github.com/suiflex/suitest && cd suitest
cp .env.example .env
```

**Edit `.env`** — set a super-admin:

```bash
SUITEST_AUTH_SECRET=<32-char-random-hex>     # generate: openssl rand -hex 32
SUITEST_SUPERADMIN_EMAIL=admin@example.com
SUITEST_SUPERADMIN_PASSWORD=<strong-password>
```

**Run it:**

```bash
make docker-up            # pull images and boot the stack
open http://localhost:3000
```

> 💡 **What is Docker Compose?** Docker runs apps in "containers" (isolated environments). Docker Compose makes it easy to run multiple containers together. If you don't have Docker, install it from [docker.com](https://docker.com).

### 4. ☸️ Kubernetes — Helm

For deploying to a Kubernetes cluster:

```bash
helm install suitest infra/helm/suitest -f infra/helm/suitest/values.yaml
```

> 💡 **Requires:** Kubernetes cluster + Helm + PostgreSQL/Redis/object storage as external services.

### 5. 🔧 Local Development (For Contributors)

If you want to contribute to Suitest:

```bash
# Requires: Python 3.12 + uv, Node 20 + pnpm, PostgreSQL/Redis/MinIO
make setup     # copy .env → install deps → run migrations → seed DB
make dev       # start API (:4000) + web (:3000) + runner together
```

**Other useful commands:**

| Command | What it does |
|---------|--------------|
| `make dev-api` | Start API only |
| `make dev-web` | Start web only |
| `make dev-runner` | Start runner only |
| `make migrate` | Run database migration |
| `make seed` | Load demo data |
| `make ci` | Lint + typecheck + tests (same as CI) |
| `make help` | See all commands |

---

## One Suitest product

Suitest is one free, self-hosted product. Login, workspace management, LLM
Settings, and manual Test Case Management work before an LLM is connected.

MCP execution, test runs, and AI features start after an administrator saves and
validates a workspace LLM in **Settings → LLM**. Ollama, llama.cpp, vLLM, LM
Studio, Anthropic, OpenAI, Gemini, Groq, OpenRouter, and custom
OpenAI-compatible endpoints all unlock the same product features.

Suitest Cloud is the future Suitest-hosted collaboration service. It is **Coming
Soon** and is separate from the model provider you connect.

---

## Your First Test

From a fresh install, you can bootstrap and run a real browser test:

1. **Log in** and create a project, suite, and manual test case.
2. Open **Settings → LLM**, save a provider, and run **Test connection**.
3. Add executable steps targeting an MCP provider such as `playwright-mcp`.
4. **Click "Run"** — the runner executes each step through MCP.
5. Review live status, evidence, and defects on the run detail page.

> 💡 **This entire journey is tested with a real Playwright suite** — `make e2e-real`

---

## Connect Your LLM

LLMs are configured **per workspace from the web UI** — `Settings → LLM` — not via env files.

**How to activate:**
1. Go to **Settings → LLM**
2. Choose a provider (Anthropic, OpenAI, Gemini, Groq, Ollama, etc.)
3. Enter your API key (encrypted with AES-GCM, never shown again)
4. Click **Test connection**; successful validation enables MCP, runs, and AI

**Supported providers:**

| Provider type | Providers |
|---------------|-----------|
| **Hosted API** | Anthropic, OpenAI, Gemini, Groq, OpenRouter, DeepSeek, etc. (100+ via LiteLLM) |
| **Self-hosted model** | Ollama, llama.cpp, vLLM, LM Studio |
| **Custom** | Any OpenAI-compatible URL (gateways, routers, proxies) |

> No LLM call is made until a workspace explicitly configures a provider.

---

## Repository Structure

```
suitest/
├── README.md                ← you are here
├── CLAUDE.md                ← coding rules for AI agents
├── Makefile                 ← all dev commands (make help)
│
├── apps/
│   ├── web/                 ← Frontend (Vite + React 19)
│   ├── api/                 ← Backend (FastAPI Python)
│   └── runner/              ← Worker that runs tests via MCP
│
├── packages/
│   ├── agent/               ← AI agent (LiteLLM + LangGraph)
│   ├── db/                  ← Database (SQLAlchemy + Alembic)
│   ├── mcp/                 ← MCP client + registry + bundled providers
│   ├── lifecycle/           ← MCP server: analyze→generate→run→publish
│   ├── mcp-npx/             ← @suiflex/suitest-mcp (npm launcher)
│   ├── suitest-npx/         ← @suiflex/suitest (one-command launcher)
│   ├── shared/              ← Shared Pydantic schemas
│   └── core/                ← Capability resolver, autonomy, crypto
│
├── sdk/
│   ├── python/              ← Python SDK (REST client)
│   └── typescript/          ← TypeScript SDK
│
├── infra/
│   ├── docker/              ← Dockerfile per service
│   └── helm/suitest/        ← Helm chart
│
└── docs/                    ← Full documentation
```

---

## Documentation

**Start at [docs/ROADMAP.md](./docs/ROADMAP.md)** — the single entry point for all features.

| Document | Topic | Who is it for? |
|----------|-------|----------------|
| [ROADMAP.md](./docs/ROADMAP.md) | Milestones M0 → M15 + build status | Developers who want to contribute |
| [PRODUCT.md](./docs/PRODUCT.md) | Vision, personas, user journeys | Product Managers, QA Leads |
| [ARCHITECTURE.md](./docs/ARCHITECTURE.md) | Stack, services, topology | Developers, DevOps |
| [DATA_MODEL.md](./docs/DATA_MODEL.md) | Database schema + entity diagram | Backend Developers |
| [API.md](./docs/API.md) | REST + WebSocket contract | Frontend Developers, API consumers |
| [UI_SPEC.md](./docs/UI_SPEC.md) | Per-screen component spec | Frontend Developers, Designers |
| [MCP_PLUGINS.md](./docs/MCP_PLUGINS.md) | MCP registry + routing + security | Developers, DevOps |
| [GENERATORS.md](./docs/GENERATORS.md) | Generator design (deterministic + LLM) | QA Engineers, Developers |
| [AUTONOMY.md](./docs/AUTONOMY.md) | Per-workspace autonomy dial | Admins, QA Leads |
| [AI_AGENT.md](./docs/AI_AGENT.md) | Prompts + LangGraph + tool registry | AI/ML Engineers |
| [BLACKBOX_UI_TESTING.md](./docs/BLACKBOX_UI_TESTING.md) | Blackbox DOM engine | QA Engineers (test from URL only) |
| [DESKTOP_TESTING.md](./docs/DESKTOP_TESTING.md) | Desktop targets (computer-use, Electron, Slint) | QA Engineers (test desktop apps) |
| [DEPLOYMENT.md](./docs/DEPLOYMENT.md) | Compose / Helm / air-gapped | DevOps, SRE |
| [TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md) | Technical FAQ & common fixes | Everyone |

---

## FAQ (Frequently Asked Questions)

### ❓ Is Suitest free?
**Yes.** Suitest is open-source (Apache 2.0 License). No subscription fees. You can self-host without limits.

### ❓ Do I need to know how to code to use Suitest?
**No.** Create and manage test cases from the web dashboard. Executing them requires a validated workspace LLM and MCP provider.

### ❓ Do I need AI/LLM to use Suitest?
**For manual TCM, no.** MCP execution, test runs, and AI features require a validated workspace LLM.

### ❓ How do I install Suitest?
See [Get Started in 3 Steps](#get-started-in-3-steps) above. Just one command: `npx @suiflex/suitest onboard`

### ❓ Is my data safe?
**Yes.** Suitest is self-hosted — your data never leaves your server. API keys are encrypted with AES-GCM. No mandatory telemetry.

### ❓ Can Suitest test things other than browsers?
**Yes.** Suitest can test: browsers (Playwright), APIs (HTTP/GraphQL/gRPC), databases (Postgres/Mongo/MySQL), mobile (Appium), desktop (Slint, Tauri), infrastructure (Kubernetes), and other MCP servers.

### ❓ What if I'm stuck / get an error?
Check [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md) or open an issue at [GitHub Issues](https://github.com/suiflex/suitest/issues).

### ❓ How do I contribute?
Read [CONTRIBUTING.md](./CONTRIBUTING.md). In short:
1. Read [CLAUDE.md](./CLAUDE.md) — coding rules
2. Pick an unchecked item in [ROADMAP.md](./docs/ROADMAP.md)
3. Branch: `feat/<scope>-<short-desc>`
4. Commits: conventional commits (`feat(api): ...`)
5. Make sure `make ci` passes before pushing

### ❓ Is there a demo I can try?
**Yes.** Run `make demo` → open `http://localhost:3000` → login `demo@suitest.dev` / `demo1234`

### ❓ Port 4000 is already in use, what do I do?
Use the `--port` flag: `npx @suiflex/suitest onboard --port 5000`

### ❓ Does Suitest work on Windows?
**Yes.** Suitest supports Windows, macOS, and Linux. Make sure Node.js ≥ 18 and uv are installed.

---

## Feature Comparison

| Feature | TestRail | Playwright | TestSprite | **Suitest** |
|---------|:--------:|:----------:|:----------:|:-----------:|
| Manual Test Case Management | ✅ | ❌ | Partial | ✅ |
| Automated Runner | ❌ | ✅ | ✅ | ✅ |
| Universal MCP Plugin Layer | ❌ | ❌ | Partial | ✅ |
| AI Generation / Diagnosis | ❌ | ❌ | ✅ | ✅ |
| Self-host | ✅ | ✅ | ❌ | ✅ |
| BYO LLM (100+ providers) | n/a | n/a | ❌ Locked | ✅ |
| Air-gapped | ✅ | ✅ | ❌ | ✅ (self-hosted model) |
| Open Source | ❌ | Runner only | ❌ | ✅ |

---

## Releases

The whole workspace shares one version and ships on one `vX.Y.Z` tag. The two
packages you install directly:

| Package | What it carries | Update with |
|---------|----------------|-------------|
| [`@suiflex/suitest`](https://www.npmjs.com/package/@suiflex/suitest) (launcher) | Local platform: web dashboard + all Python wheels | `npx @suiflex/suitest@latest onboard` |
| [`@suiflex/suitest-mcp`](https://www.npmjs.com/package/@suiflex/suitest-mcp) (MCP server) | IDE tools + lifecycle engine | `npx -y @suiflex/suitest-mcp@latest` |

**Release notes:** [suitest.suiflex.dev/docs/changelog](https://suitest.suiflex.dev/docs/changelog/)

---

## Contributing

1. **Read [CLAUDE.md](./CLAUDE.md)** — coding conventions (also applies to AI coding agents)
2. **Pick the next unchecked item in [docs/ROADMAP.md](./docs/ROADMAP.md)** — one PR = one acceptance criterion
3. **Branch:** `feat/<scope>-<short-desc>`. **Commits:** conventional commits (`feat(api): ...`)
4. **Before pushing:** `make ci` must pass (ruff + mypy strict, tsc strict + ESLint, pytest async + vitest)

See also [CONTRIBUTING.md](./CONTRIBUTING.md), [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md), and [SECURITY.md](./SECURITY.md).

---

## License

Apache License 2.0. See [LICENSE](./LICENSE).

## Acknowledgments

Built on [Model Context Protocol](https://modelcontextprotocol.io) (Anthropic), [LiteLLM](https://github.com/BerriAI/litellm) (BerriAI), [LangGraph](https://langchain-ai.github.io/langgraph/) (LangChain), [`@ai-sdk/react`](https://sdk.vercel.ai/docs) + assistant-ui (Vercel), shadcn/ui, TanStack, and the FastAPI / SQLAlchemy / Pydantic ecosystems.

---

<p align="center">
  <a href="https://suiflex.dev">
    <img src="docs-site/public/assets/brand/suiflex-logo-mark.png" alt="Suiflex" width="40">
  </a>
</p>
<p align="center">
  <sub><strong>Suitest</strong> is a <a href="https://suiflex.dev">Suiflex</a> project — powered by Suiflex.</sub>
</p>
