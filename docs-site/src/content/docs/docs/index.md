---
title: Suitest documentation
description: Self-hostable open-source QA platform. Manual test management, a deterministic MCP-driven runner, and optional bring-your-own-LLM AI.
---

Suitest is a self-hostable, open-source QA platform (Apache-2.0, pre-v1.0). It works fully without an LLM and adds AI only when you configure one:

- **Manual test case management.** Projects, suites, cases with steps, runs, rule-based defects, traceability, analytics, CI webhooks.
- **Deterministic runner via MCP.** Every test step dispatches through an MCP provider (`playwright`, `api-http`, `postgres`), with live logs, screenshots, and per-test video evidence.
- **Optional BYO-LLM AI.** Configure any provider per workspace from the web UI (Anthropic, OpenAI, Gemini, local Ollama or vLLM, or any OpenAI-compatible URL) to unlock agent chat, PRD-driven generation, and LLM codegen. No key is ever required.
- **MCP server for IDE agents.** `npx -y @suiflex/suitest-mcp` gives Claude Code, Cursor, or Codex a full testing lifecycle: analyze, generate, run, report, publish.
- **Blackbox DOM engine.** Test any web app from just a URL and test credentials: login detection, safe crawling, deterministic Playwright generation, evidence. No repo access needed.

## Who it is for

- **Developers using AI coding agents** who want the agent to verify its own work: generate tests, run them, read failures, fix the code, re-run until green.
- **QA engineers** who need managed test cases, deterministic execution, and evidence without vendor lock-in or per-seat SaaS pricing.
- **Small teams** with no dedicated QA who want real testing structure that costs nothing to run at the ZERO tier.

## Choose your path

### I want to test from my IDE

Connect your coding agent to Suitest in one command. No platform install required.

```bash
npx -y @suiflex/suitest-mcp init
```

- [Install the MCP server](/docs/install/mcp-server/)
- [Agent workflow](/docs/guides/agent-workflow/)
- [Blackbox testing from a URL](/docs/guides/blackbox-testing/)
- [MCP tool reference](/docs/reference/mcp-tools/)

### I want the full platform

Run the web TCM, API, runner, and storage yourself.

```bash
docker compose up -d
```

- [Getting started](/docs/guides/getting-started/)
- [Docker Compose install](/docs/install/docker/)
- [Kubernetes (Helm)](/docs/install/kubernetes/)
- [Self-hosting guide](/docs/guides/self-hosting/)
- [First test tutorial](/docs/guides/tutorial/)

### I want CI

Gate merges on test results and post a PR comment from your pipeline.

```bash
npx -y @suiflex/suitest-mcp ci --config suitest.config.json
```

- [GitHub Action guide](/docs/guides/ci-github-action/)
- [CLI reference](/docs/reference/cli/)

## Learn the concepts

- [How it works](/docs/concepts/how-it-works/): the analyze, generate, run, report lifecycle.
- [Data model](/docs/concepts/data-model/): workspaces, projects, suites, cases, runs, defects.
- [Evidence](/docs/concepts/evidence/): screenshots, video, logs, and where they are stored.
- [Capability tiers](/docs/reference/tiers/): what ZERO, LOCAL, and CLOUD unlock.

## Reference

- [MCP tools](/docs/reference/mcp-tools/): all 22 tools the IDE agent gets.
- [CLI](/docs/reference/cli/): the npx launcher, the lifecycle CLI, and the platform CLI.
- [Configuration](/docs/reference/configuration/): every `suitest.config.json` field.
- [REST API](/docs/reference/api/): endpoint tour and authentication.
- [Environment variables](/docs/reference/environment/): API, runner, CLI, and MCP settings.

## Help

- [Troubleshooting](/docs/help/troubleshooting/)
- [FAQ](/docs/help/faq/)

:::note
Suitest is pre-v1.0 and under active development. The ZERO tier (no LLM) is the default everywhere: no LLM call is ever made until a workspace explicitly configures a provider. See [LLM setup](/docs/guides/llm-setup/) when you want AI features.
:::
