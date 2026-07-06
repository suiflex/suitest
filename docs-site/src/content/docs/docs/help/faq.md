---
title: FAQ
description: Frequently asked questions about Suitest licensing, LLM requirements, supported IDEs, data privacy, CI, and how it compares to other tools.
---

## Is Suitest free?

Yes. Suitest is open source under the Apache-2.0 license and designed to be self-hosted. There is no hosted billing, no per-seat pricing, and the ZERO tier costs nothing to run: no LLM bill, ever.

## Do I need an LLM API key?

No. The entire deterministic core works with no LLM at all: manual test case management, the MCP-driven runner, deterministic generators (OpenAPI, browser recorder, crawler), the blackbox engine, rule-based defects, traceability, and analytics. AI features are an optional layer on top. See [Capability tiers](/docs/reference/tiers/).

## Can I use my Claude or Cursor subscription instead of an API key?

The MCP server includes support for MCP sampling: when your MCP client advertises the sampling capability, the server can route LLM requests through the agent's own model, which means your existing AI subscription instead of a separate key. Where no LLM is reachable, LLM-assisted features degrade to the deterministic baseline instead of failing.

## Which IDEs are supported?

Anything that speaks MCP. The installer has first-class targets for Claude Code, Claude Desktop, Cursor, Windsurf, Codex, Gemini CLI, VS Code (Copilot), Copilot CLI, opencode, and Antigravity, plus a `generic-json` target that prints a portable snippet for anything else. See [Install the MCP server](/docs/install/mcp-server/).

## Can Suitest test an app it has no source code for?

Yes. The blackbox DOM engine tests any web app from just a URL and test credentials: it detects the login form heuristically, logs in, crawls routes safely (destructive controls are skipped by default), generates deterministic Playwright tests, and records evidence. No repo access, no LLM key. See [Blackbox testing](/docs/guides/blackbox-testing/).

## What data leaves my machine?

By default, nothing. The platform is self-hosted (your Postgres, your Redis, your MinIO/S3), and no LLM call is ever made until a workspace configures a provider. The MCP server publishes cases, runs, and evidence only to the Suitest server you point it at with `SUITEST_API_URL`. If you configure a cloud LLM, prompts for AI features go to that provider; choose a local model (Ollama, vLLM) to keep inference on your hardware.

## How is Suitest different from TestRail?

TestRail is manual test management only: no runner, closed source. Suitest gives you comparable TCM (cases, suites, runs, traceability, analytics) plus a deterministic execution engine and evidence, self-hosted and open source.

## How is Suitest different from Playwright?

Playwright is a test runner, and an excellent one; Suitest builds on it rather than competing with it. Suitest adds the workflow layer around runners: deciding what to test, managing cases, executing steps through MCP providers (browser, HTTP, database), collecting evidence, and reporting.

## How is Suitest different from TestSprite?

TestSprite is closed source, cloud-only, and requires an LLM API key. Suitest is Apache-2.0, self-hostable (including air-gapped), fully functional with no LLM, and lets you bring any LLM you want when you do want AI.

## Is Suitest production-ready?

Suitest is pre-v1.0 and under active development. The core loop is exercised end to end (TCM, runner, evidence, MCP server, blackbox engine, CI gate), but expect breaking changes before 1.0. Pin versions and read release notes when upgrading.

## Where is evidence stored?

Platform runs upload screenshots, videos, HARs, and logs through the API into object storage (MinIO by default, any S3-compatible store in production). Local lifecycle and blackbox runs keep everything under `suitest-output/` next to your config; when publishing is configured, evidence is uploaded to the server as well. See [Evidence](/docs/concepts/evidence/).

## Does Suitest work in CI?

Yes. `npx -y @suiflex/suitest-mcp ci` runs the lifecycle, posts a PR comment, and exits `0` (pass), `1` (test failure), or `2` (infra error), so it works as a merge gate. The platform also emits CI webhooks and integrates with GitHub, GitLab, Jira, and Slack. See [CI with GitHub Actions](/docs/guides/ci-github-action/).

## What can Suitest test?

Web UIs (through the `playwright` MCP provider), REST APIs (`api-http`), and Postgres (`postgres`) out of the box. Because every step dispatches through an MCP provider, you can register additional providers to reach other targets. See the [API reference](/docs/reference/api/) for provider management endpoints.

## Can I run Suitest air-gapped?

Yes. Docker Compose ships an optional Ollama profile for local inference, and the Helm chart has an air-gapped values file. At the ZERO tier no external calls are needed at all. See [Self-hosting](/docs/guides/self-hosting/).

## What happens when a test fails?

A failing step files a defect automatically (rule-based at the ZERO tier), and the failure is linked to its evidence. For coding agents, the `get_failure_context` MCP tool returns a compact markdown bundle (error, failed step, DOM excerpt, console, network, evidence links) sized to fit an agent context window, so the agent can diagnose and fix without opening screenshots by hand. See [Failure context](/docs/guides/failure-context/).

## How do I contribute?

Read `CLAUDE.md` (the binding repo conventions) and `docs/ROADMAP.md` (the single source of truth for build status), pick the next unchecked acceptance criterion, and open one PR per criterion. `make ci` must pass before pushing. The repo also has `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `SECURITY.md`.
