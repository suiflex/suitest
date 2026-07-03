---
title: Capability tiers
description: ZERO / LOCAL / CLOUD and what each unlocks.
---

| Tier | LLM | Unlocks |
|------|-----|---------|
| **ZERO** | none | Manual TCM, deterministic MCP runs, rule-based defect filing, lexical search |
| **LOCAL** | local (Ollama/vLLM/llama.cpp/LM Studio) | AI generation, diagnosis, chat, `fastembed` semantic search — air-gappable |
| **CLOUD** | BYO cloud key | Same AI features via a hosted provider |

The tier is resolved from your LLM configuration; AI features are gated behind it
and degrade gracefully when no LLM is present.
