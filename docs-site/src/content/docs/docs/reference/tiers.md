---
title: Capability tiers
description: ZERO, LOCAL, and CLOUD in depth, how the tier is resolved from workspace LLM settings, the full feature matrix, and the autonomy levels.
---

Suitest runs in three capability tiers: **ZERO**, **LOCAL**, and **CLOUD**. They are not pricing tiers. Same binary, same deployment; the tier is a capability matrix determined by whether, and how, your workspace has an LLM configured.

The design principle: the deterministic core (test case management, deterministic runs, evidence, reporting) works at every tier. AI features stack on top when an LLM is present, and never replace the deterministic path.

## The three tiers

| Tier | LLM | Who it is for |
|------|-----|---------------|
| **ZERO** | None | Air gapped and regulated environments, or anyone who wants a TCM plus deterministic runner with no AI. The default: first boot works with no configuration. |
| **LOCAL** | Self hosted (Ollama, llama.cpp, vLLM, LM Studio) | Teams with on premise GPUs. Full AI features with no egress; still air gap friendly. |
| **CLOUD** | Bring your own key (Anthropic, OpenAI, Gemini, Groq, OpenRouter, Azure, Bedrock, Vertex, DeepSeek) | Teams with a SaaS API budget. Full AI features; requires egress to the provider. |

## How the tier is resolved

The tier comes from the **per workspace LLM configuration in the web UI**, not from environment variables. There are no `SUITEST_LLM_*` environment variables; the base deployment is always ZERO.

Resolution happens in two layers:

1. **Base (deployment wide).** The capability resolver always returns ZERO. It does not read any environment.
2. **Overlay (per workspace).** The API reads the workspace's active LLM configuration on every request and raises the effective tier from the configured provider:

```text
provider is empty, "none", or "disabled"          -> ZERO
provider in {ollama, llamacpp, vllm, lmstudio}    -> LOCAL
any other provider (anthropic, openai, gemini,
  groq, openrouter, azure, bedrock, vertex,
  deepseek, mock)                                 -> CLOUD
```

To change your tier, open **Settings, then LLM provider** in the dashboard:

1. Pick a provider and enter the model, plus an API key (cloud providers) or a base URL (local providers).
2. Click **Test connection**. The configuration must validate before it can be saved.
3. Save. The API key is stored AES-GCM encrypted in the database and is never returned by the API.

The change takes effect **immediately, per workspace, without a restart**. Because the overlay reads the database on every request, the next `GET /capabilities` call already reflects the new tier, and action only test steps become executable the moment a LOCAL or CLOUD provider is active. Every configuration change is written to the audit log. See [LLM setup](/docs/guides/llm-setup/) for provider specifics.

:::note
The `mock` provider returns canned deterministic responses for CI and development without real API spend. It resolves to CLOUD (full feature surface) but is flagged `is_test_provider: true` in the capabilities response, and the UI shows a "test provider" banner.
:::

## Feature matrix

| Feature | ZERO | LOCAL | CLOUD |
|---------|------|-------|-------|
| Manual TCM (suites, cases, steps, tags, traceability) | Yes | Yes | Yes |
| Deterministic runs (steps with `code`, via MCP providers) | Yes | Yes | Yes |
| MCP plugins (bundled and custom providers) | Yes | Yes | Yes |
| Deterministic generators (OpenAPI, recorder, crawler) | Yes | Yes | Yes |
| Defect filing, rule based | Yes | Yes | Yes |
| Full text search | Yes | Yes | Yes |
| Webhooks, analytics, traceability matrix | Yes | Yes | Yes |
| AI test generation (PRD, semantic URL, MCP discovery) | No | Yes | Yes |
| Agentic step execution (action only steps translated at runtime) | No | Yes | Yes |
| AI diagnosis (failure classification and root cause narration) | No | Yes | Yes |
| Agent chat panel | No | Yes | Yes |
| Defect filing with AI reasoning | No (rule based fallback) | Yes | Yes |
| Autonomy levels available | `manual` only | All four | All four |
| Egress required | No | No | Yes, to the LLM provider |
| Air gap friendly | Yes | Yes | No (except Bedrock or Vertex in VPC) |

Semantic search is an independent dial: it depends on an embeddings backend, not on the LLM tier, and is disabled in the base deployment. Full text search always works.

## Autonomy levels

Autonomy is a separate per workspace dial that controls how much the agent may do without asking. Four levels:

| Level | Meaning |
|-------|---------|
| `manual` | Every action is user initiated. No agentic operations run on their own. |
| `assist` | AI features run when invoked: generation, diagnosis, and runtime translation of action only steps. |
| `semi_auto` | Adds combined gates such as automatic failure categorization with automatic rerun. |
| `auto` | Reserved for fully autonomous flows such as self healing tests. |

Availability and defaults per tier:

| Tier | Available levels | Default |
|------|------------------|---------|
| ZERO | `manual` | `manual` |
| LOCAL | `manual`, `assist`, `semi_auto`, `auto` | `assist` |
| CLOUD | `manual`, `assist`, `semi_auto`, `auto` | `assist` |

ZERO is locked to `manual` because there is no LLM to act autonomously. Agentic operations with side effects require both a sufficient tier and a sufficient autonomy level.

## How the runner behaves per tier

The tier changes what happens to a step that has no executable `code`:

```text
step has code?
  yes -> execute deterministically via its MCP provider
         outcome: pass | fail | error
  no  -> tier ZERO           -> step skipped
                                 reason: NO_LLM_FOR_AGENTIC_STEP
         tier LOCAL / CLOUD  -> requires autonomy assist or higher,
                                 then the step's action is translated
                                 to code at runtime and executed via MCP
```

A run where steps were skipped (and nothing failed) finishes as a partial result rather than a failure: in ZERO this is expected for action only cases, and the UI points at the tier instead of showing red.

Two related behaviors:

- **Validation at save time.** With the workspace setting `strict_zero_validation` enabled (the default), a ZERO workspace rejects saving a test step that has no `code`, since nothing could ever execute it. Disable the setting to stage action only cases first (for example when importing from another TCM) and upgrade the tier later.
- **Tier stamped on runs.** Every run records `tier_at_runtime`, so historical results remain interpretable after you change providers. A rerun re resolves the current workspace tier.

## Checking the current tier

`GET /capabilities` is public (the UI fetches it before login) and returns the effective tier, the active provider info, a feature flag map, the available autonomy levels, and the registered MCP providers. The dashboard uses it to render the tier badge in the top bar and to gate AI features: at ZERO, AI panels are hidden or shown with an upgrade hint instead of failing silently.

See the [API reference](/docs/reference/api/) for the full response shape.

:::caution
Suitest is pre 1.0. The tier contract described here is stable in intent, but per endpoint gating details may still change between releases. The `/capabilities` response is the source of truth for what your instance supports.
:::

## Which tier do I need?

| I want to... | Minimum tier |
|---------------|-------------|
| Replace a classic TCM (manual cases, suites, traceability) | ZERO |
| Run deterministic browser, API, and DB tests | ZERO |
| Import an OpenAPI spec and generate contract tests | ZERO |
| Record a browser session into a Playwright test | ZERO |
| Crawl a URL into a skeleton smoke suite | ZERO |
| Generate test cases from a natural language PRD | LOCAL or CLOUD |
| Run cases whose steps are plain actions ("click the login button") | LOCAL or CLOUD |
| Get an AI narrative of why a test failed | LOCAL or CLOUD |
| Auto categorize failures and auto rerun | LOCAL or CLOUD, autonomy `semi_auto` |
| Full AI with zero egress | LOCAL |
| Try Suitest in five minutes | ZERO |

## Next steps

- [LLM setup](/docs/guides/llm-setup/): configuring a provider per workspace
- [How Suitest works](/docs/concepts/how-it-works/): where the tier sits in the pipeline
- [Agent workflow](/docs/guides/agent-workflow/): what LOCAL and CLOUD unlock in practice
