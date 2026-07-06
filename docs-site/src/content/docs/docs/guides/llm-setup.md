---
title: Bring your own LLM
description: Three ways Suitest gets inference, MCP sampling on your subscription, a workspace LLM bridge, or none at all, and the fallback order.
---

Suitest never ships with an LLM key and never requires one. Inference, when it
happens at all, comes from one of three places, tried in a fixed order. The
deterministic baseline works with no LLM whatsoever, so every path below is
enrichment, not a dependency.

## The three inference paths

### 1. MCP sampling: your agent's own model, no API key

When the connected MCP client (for example Claude Code) advertises the
`sampling` capability at initialize, the Suitest MCP server can send a
`sampling/createMessage` request back through the client. The completion runs
on the user's own model subscription. No OpenAI or Anthropic key is held by
Suitest, nothing is configured, and there is no separate bill.

- Detected automatically: if your client supports sampling, this path is
  first in line.
- Requests carry the prompt, an optional system prompt, and a max token
  count; the default timeout is 180 seconds.
- A sampling failure (timeout, client error, empty content) is never fatal.
  The chain falls through to the next tier.

### 2. The workspace LLM bridge

The lifecycle can call `POST /api/v1/llm/complete` on the Suitest server,
authenticated with the same `SUITEST_API_KEY` used for publishing. The server
runs the completion against the workspace's active LLM configuration, which an
admin sets in the web UI under **Settings, LLM**. The lifecycle side never
sees the provider key.

Supported providers:

| Provider value | Tier | Requirements |
|----------------|------|--------------|
| `ollama`, `llamacpp`, `vllm`, `lmstudio` | LOCAL | `base_url` required, no API key |
| `anthropic`, `openai`, `gemini`, `groq`, `openrouter`, `azure`, `deepseek` | CLOUD | API key required |
| `bedrock`, `vertex` | CLOUD | no key in Suitest (IAM or ambient credentials) |
| `custom` | CLOUD | any OpenAI-compatible endpoint; `base_url` required, key optional (gateway-dependent) |
| `mock` | CLOUD (test flag) | canned deterministic responses for CI and dev, flagged `is_test_provider` |

Configuration facts:

- **Per workspace.** Each workspace has its own active config; switching
  provider takes effect immediately, with no restart and no env vars.
- **Test-connected before save.** The API validates the provider, model, key,
  and base URL, and runs a connection test through the provider layer.
- **AES-encrypted at rest.** The key is stored AES-GCM encrypted in the
  database under `SUITEST_ENCRYPTION_KEY`; the UI only ever shows a redacted
  hint like `sk-a...st4v`.
- **No LLM configured.** The server answers `409` to `/llm/complete`, and the
  lifecycle stops asking and degrades cleanly.

### 3. No LLM at all: the deterministic baseline

The ZERO tier is the default and is fully functional: manual TCM, the
deterministic runner, MCP providers, deterministic test generation (including
the whole [blackbox engine](/docs/guides/blackbox-testing/)), reports, and
publishing all work with zero egress. Air-gapped deployments run this way
permanently.

## Fallback order

The lifecycle assembles a chain at generation time:

```text
MCP sampling  ->  workspace bridge  ->  deterministic baseline
```

- Sampling is included only when the connected client advertised the
  capability.
- The bridge is included only when `SUITEST_API_URL` and `SUITEST_API_KEY`
  resolve (from the config's publish section or the environment).
- The first non-empty answer wins. Any failure returns an empty answer and
  the chain moves on. When no client is available at all, the caller keeps
  the deterministic baseline.

Every generation envelope reports where inference came from, so you can audit
it: `llm_source` is `"sampling"`, `"bridge"`, or `"deterministic"`, with the
model name when sampling was used.

:::tip
A Claude Pro or Copilot user connecting through Claude Code gets AI-assisted
planning and codegen billed to their existing subscription, with no key
configured anywhere. That is the sampling path doing its job.
:::

## Tier gating

The workspace LLM configuration is what sets the capability tier:

| Tier | Trigger | AI features |
|------|---------|-------------|
| ZERO | no provider set | off; everything deterministic still works |
| LOCAL | `ollama` / `llamacpp` / `vllm` / `lmstudio` | on, no egress |
| CLOUD | any cloud provider or `custom` | on, egress to the provider |

Features that require inference (PRD generation, semantic URL generation,
AI diagnosis, chat) are gated by tier and answer `503 LLM_DISABLED` below
their minimum; the UI shows the tier badge in the topbar and gates the same
features with tooltips. The full matrix lives in the
[tiers reference](/docs/reference/tiers/).

## What the LLM is actually used for

When a chain is available, the lifecycle uses it for three things:

- **Edge-case enrichment**: proposing up to five additional high-value test
  cases on top of the deterministic plan.
- **PRD-driven planning**: turning an uploaded markdown PRD plus the
  discovered app reality into a semantic test plan.
- **Frontend codegen**: writing the Playwright test body for apps that follow
  no testid convention, from the crawled DOM digest.

Generated code is never trusted blindly. Each body passes a structural gate
(must have the expected shape, no imports, no known runtime landmines, must
compile) and anything that fails the gate falls back to the deterministic
version. A weak model can lower the quality of enrichment; it cannot break
the baseline.

## Choosing a path

| You are | Recommended setup |
|---------|-------------------|
| An individual with an AI subscription in your IDE | Nothing to configure: sampling handles it |
| A team self-hosting with an API budget | Set a cloud provider in Settings, LLM |
| A team with on-prem GPUs or privacy requirements | Run Ollama or vLLM and set a LOCAL provider; see [Self-hosting](/docs/guides/self-hosting/) |
| Air-gapped or just evaluating | Stay on ZERO; everything deterministic works |

For connecting the IDE side in the first place, see
[Install the MCP server](/docs/install/mcp-server/).
