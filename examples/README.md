# Suitest examples (M4-15)

Runnable starting points for common Suitest workflows. Each directory has its own
README with step-by-step instructions.

| Example | What it shows | Tier |
|---------|---------------|------|
| [`playwright-e2e`](./playwright-e2e) | Browser E2E via the `playwright-mcp` provider | ZERO |
| [`openapi-contract`](./openapi-contract) | Generate a contract suite from an OpenAPI spec | ZERO |
| [`mixed-mcp-e2e`](./mixed-mcp-e2e) | One test case spanning Postgres + HTTP + browser MCPs | ZERO |
| [`air-gapped-deploy`](./air-gapped-deploy) | Self-host with no outbound network + in-cluster Ollama | LOCAL |

All examples run at ZERO tier (no LLM) except `air-gapped-deploy`, which adds a
LOCAL model. Set `SUITEST_API_URL` / `SUITEST_TOKEN` / `SUITEST_WORKSPACE_ID` and
use the `suitest` CLI or the SDKs.
