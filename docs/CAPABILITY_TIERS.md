# LLM readiness and feature gating

> Current contract. The former ZERO / LOCAL / CLOUD capability tiers were removed.
> Provider location is not a product tier: Ollama and hosted model APIs follow the
> same readiness lifecycle.

## Workspace states

| `llm.status` | Meaning | Runs & MCP | AI features |
|---|---|---|---|
| `not_configured` | No active workspace LLM configuration | Deterministic runs & tools enabled | blocked |
| `validation_required` | Saved or changed but not connection-tested | Deterministic runs & tools enabled | blocked |
| `ready` | Active configuration has `last_validated_at` | All runs & tools enabled | enabled |

Manual web TCM, deterministic test execution (Playwright, API HTTP, Postgres,
etc.), MCP provider operations, authentication, workspace management, and LLM
Settings remain available in every state. AI-specific workflows (agentic test
generation, runtime step translation, AI defect diagnosis, and prompt experiments)
require `ready`.
## Source of truth

The active `llm_configs` row is the source of truth. Provider credentials are
stored encrypted with AES-GCM and never returned to the browser or MCP client.
Saving or changing a provider clears `last_validated_at`; a successful connection
test sets it. Startup uses that persisted result and does not spend a completion
merely to probe readiness.

`GET /capabilities` exposes `llm.status` and feature flags, not a tier. API gates
return `409 LLM_NOT_READY` with the current status and a Settings link.

## MCP contract

The client config contains only `SUITEST_API_URL` and `SUITEST_API_KEY`. Startup
authenticates credentials via `/api/v1/api-keys/whoami`. LLM work is proxied
through `/api/v1/llm/complete`; MCP sampling and local fallback chains do not exist.
## Product packaging

The current release is the free self-hosted product. “Suitest Cloud” is reserved
for a future Suitest-hosted collaboration service and is **Coming Soon**. It is
not an LLM-provider category, capability state, or pricing switch. Enterprise
packaging is intentionally out of scope.
