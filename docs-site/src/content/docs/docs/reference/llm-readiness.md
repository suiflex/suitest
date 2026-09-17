---
title: LLM readiness
description: How workspace LLM validation controls MCP, runs, and AI features without product editions.
---

Suitest is one product. Provider location and authentication method do not
create separate editions: hosted APIs, self-hosted models, and supported sign-in
providers unlock the same feature surface after validation.

## Workspace states

| `llm.status` | Meaning | Runs & MCP | AI features |
|---|---|---|---|
| `not_configured` | No active workspace LLM configuration | Deterministic runs & tools enabled | Blocked |
| `validation_required` | Saved or changed but not connection-tested | Deterministic runs & tools enabled | Blocked |
| `ready` | Active configuration has a successful `last_validated_at` result | All runs & tools enabled | Enabled |

Manual test case management, deterministic test execution (Playwright, API HTTP,
Postgres, etc.), MCP operations, authentication, workspace management, and LLM
settings remain available in every state. AI-specific workflows (agentic test
generation, runtime step translation, AI defect diagnosis, and prompt experiments)
require `ready`.
## Validation lifecycle

Open **Settings, then LLM**, select a provider, enter its connection details,
save the configuration, and run **Test connection**. Saving or changing a
provider clears the previous validation result. A successful test records
`last_validated_at` and enables MCP and runs immediately for that workspace.

Provider credentials are encrypted with AES-GCM and never returned to the
browser or MCP client. Startup reads the persisted validation result; it does
not spend an LLM completion merely to check readiness.

`GET /capabilities` exposes `llm.status` and feature flags. A protected API
operation returns `409 LLM_NOT_READY` when the workspace is not ready.

## MCP contract

The MCP client receives only `SUITEST_API_URL` and `SUITEST_API_KEY`. At
startup it authenticates credentials via `/api/v1/api-keys/whoami`. Completions
go through `/api/v1/llm/complete`, so provider credentials remain on the server.
MCP client-provided inference and an offline MCP mode are not supported.

## Product packaging

The current release is the free, self-hosted Suitest product. **Suitest Cloud**
is reserved for a future Suitest-hosted collaboration service and is Coming
Soon. It is not an LLM provider category, feature switch, or pricing level.

See [Bring your own LLM](/docs/guides/llm-setup/) for provider setup and
[Install the MCP server](/docs/install/mcp-server/) for client configuration.
