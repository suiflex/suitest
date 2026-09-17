---
title: FAQ
description: Frequently asked questions about Suitest licensing, LLM requirements, supported IDEs, data privacy, CI, and how it compares to other tools.
---

## Is Suitest free?

Yes. Suitest is open source under the Apache-2.0 license and designed to be self-hosted. There is no hosted billing or per-seat pricing in the current product. Model-provider costs, if any, remain between you and your provider.

## What is the fastest way to try Suitest?

`npx @suiflex/suitest onboard` boots the full platform on your laptop and wires your IDE's MCP config. No Docker is required. Then configure and validate a workspace LLM in Settings before starting MCP or a run. See [Local bundle](/docs/install/local-bundle/).

## Do I need an LLM API key?

Not necessarily an API key. Manual test case management works before an LLM is connected. MCP, runs, and AI workflows require a validated workspace provider, which may use an API key, a self-hosted base URL, or a supported sign-in flow. See [LLM readiness](/docs/reference/llm-readiness/).

## Can MCP use my Claude or Cursor model directly?

No. Suitest reads the validated LLM configuration stored for the workspace and proxies completions through its API. The MCP client receives only the Suitest API URL and key; provider credentials stay encrypted on the server.

## Which IDEs are supported?

Anything that speaks MCP. The installer has first-class targets for Claude Code, Claude Desktop, Cursor, Windsurf, Codex, Gemini CLI, VS Code (Copilot), Copilot CLI, opencode, and Antigravity, plus a `generic-json` target that prints a portable snippet for anything else. See [Install the MCP server](/docs/install/mcp-server/).

## Can Suitest test an app it has no source code for?

Yes. The blackbox DOM engine tests any web app from a URL and test credentials: it detects the login form, crawls routes safely, generates Playwright tests, and records evidence. No repo access is needed; the workspace LLM must be validated. See [Blackbox testing](/docs/guides/blackbox-testing/).

## What data leaves my machine?

The platform data stays in your self-hosted Postgres and object storage. LLM requests go only to the provider configured for the workspace; choose Ollama or vLLM to keep inference on your infrastructure. The MCP server publishes only to the Suitest API specified by `SUITEST_API_URL`.

## How is Suitest different from TestRail?

TestRail is manual test management only: no runner, closed source. Suitest gives you comparable TCM (cases, suites, runs, traceability, analytics) plus a deterministic execution engine and evidence, self-hosted and open source.

## How is Suitest different from Playwright?

Playwright is a test runner, and an excellent one; Suitest builds on it rather than competing with it. Suitest adds the workflow layer around runners: deciding what to test, managing cases, executing steps through MCP providers (browser, HTTP, database), collecting evidence, and reporting.

## How is Suitest different from TestSprite?

TestSprite is closed source and hosted. Suitest is Apache-2.0, self-hostable, and lets each workspace connect its own supported LLM provider.

## Is Suitest production-ready?

Suitest is pre-v1.0 and under active development. The core loop is exercised end to end (TCM, runner, evidence, MCP server, blackbox engine, CI gate), but expect breaking changes before 1.0. Pin versions and read release notes when upgrading.

## Where is evidence stored?

Runs upload screenshots, videos, HARs, and logs through the API into object storage (MinIO by default, any S3-compatible store in production). See [Evidence](/docs/concepts/evidence/).

## Does Suitest work in CI?

Yes. `npx -y @suiflex/suitest-mcp ci` runs the lifecycle, posts a PR comment, and exits `0` (pass), `1` (test failure), or `2` (infra error), so it works as a merge gate. The platform also emits CI webhooks and integrates with GitHub, GitLab, Jira, and Slack. See [CI with GitHub Actions](/docs/guides/ci-github-action/).

## What can Suitest test?

Web UIs (through the `playwright` MCP provider), REST APIs (`api-http`), and Postgres (`postgres`) out of the box. Because every step dispatches through an MCP provider, you can register additional providers to reach other targets. See the [API reference](/docs/reference/api/) for provider management endpoints.

## Can I run Suitest air-gapped?

Yes. Use a self-hosted model such as Ollama or vLLM and the Helm air-gapped values. The Suitest API must be able to reach that model endpoint. See [Self-hosting](/docs/guides/self-hosting/).

## What happens when a test fails?

A failing step files a defect automatically and links it to the evidence. For coding agents, the `get_failure_context` MCP tool returns a compact markdown bundle (error, failed step, DOM excerpt, console, network, evidence links) sized for an agent context window. See [Failure context](/docs/guides/failure-context/).

## How do I contribute?

Read `CLAUDE.md` (the binding repo conventions) and `docs/ROADMAP.md` (the single source of truth for build status), pick the next unchecked acceptance criterion, and open one PR per criterion. `make ci` must pass before pushing. The repo also has `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `SECURITY.md`.
