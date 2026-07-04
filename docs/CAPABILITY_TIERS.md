# docs/CAPABILITY_TIERS.md

> Complete spec of Suitest capability tiering: **ZERO / LOCAL / CLOUD**. Used as the contract between `packages/core/capabilities.py` (resolver), `apps/api` (endpoint gating), `apps/runner` (step execution), and `apps/web` (UI gating). For architecture read [ARCHITECTURE.md](./ARCHITECTURE.md). For deployment read [DEPLOYMENT.md](./DEPLOYMENT.md).

> ⚠️ **PARTIAL.** ZERO-tier resolver built (`packages/core/capabilities.py`). M3-2/M3-3 built: workspace `LLMConfig` write path recomputes `WorkspaceCapability` and `/capabilities` overlays the active config (per-workspace tier flip ZERO↔CLOUD/LOCAL); the `mock` provider works end-to-end. Still NOT built: per-feature 503 `LLM_DISABLED` enforcement in `require_tier` (decorator still records-only). See [ROADMAP.md](./ROADMAP.md) M3.

---

## 1. Concept

Suitest must work in three "operating modes":

1. **Self-host air-gapped, no LLM.** Enterprise / regulated-industry QA teams that are not allowed to egress to the cloud. Suitest must still be 100% useful as a TCM + deterministic runner.
2. **Self-host with local LLM.** Teams with on-prem GPUs (Ollama / vLLM / llama.cpp). Privacy preserved, AI features active.
3. **Self-host + cloud LLM (BYO).** Teams with a SaaS API budget — bring your own key (Anthropic / OpenAI / Gemini / etc.). Full features.

Hence the tiers are **not** pricing tiers, but a **capability matrix** determined by the per-workspace LLM configuration (web UI). Same binary, different surface area.

Principles:

- **Default = ZERO.** First boot works without any configuration — the base deployment is always ZERO.
- **Upgrade = set a provider in the web UI.** Switching tier = pick a provider in Settings → LLM (test-connected, stored AES-encrypted in the DB) — takes effect immediately per-workspace, **without restart**, no rebuild, no env.
- **No silent degradation.** If a feature is not available in the current tier, the endpoint returns `503 LLM_DISABLED` with a reason — the UI gates it with a tooltip.
- **Embeddings independent from the LLM.** The embedder runtime (`packages/core/embeddings.py`) is resolved separately; base capability embeddings = disabled until there is a workspace embeddings config.

---

## 2. Tier definition

| Aspect | ZERO | LOCAL | CLOUD |
|-------|------|-------|-------|
| Trigger (workspace LLM provider, web UI) | `none` / not set | `ollama` / `llamacpp` / `vllm` / `lmstudio` | `anthropic` / `openai` / `gemini` / `groq` / `openrouter` / `azure` / `bedrock` / `vertex` / `deepseek` / `mock` (test/dev only — see §3) |
| Manual TCM (CRUD case/suite) | ✓ | ✓ | ✓ |
| Deterministic runner (`step.code`) | ✓ | ✓ | ✓ |
| MCP plugins | ✓ | ✓ | ✓ |
| Webhook + traceability + analytics | ✓ | ✓ | ✓ |
| Defect filing (rule-based) | ✓ | ✓ | ✓ |
| Deterministic generators (OpenAPI / Recorder / Crawler) | ✓ | ✓ | ✓ |
| AI generation (PRD / URL semantic / MCP discovery) | ✗ | ✓ | ✓ |
| AI execution (agentic step translate) | ✗ | ✓ | ✓ |
| AI diagnosis (root-cause narration) | ✗ | ✓ | ✓ |
| AI conversation (chat panel) | ✗ | ✓ | ✓ |
| Embeddings (base disabled; workspace dial future) | off | off | off |
| Semantic search | only if embeddings on | ✓ if embeddings on | ✓ if embeddings on |
| FTS fallback search | ✓ (always) | ✓ | ✓ |
| Autonomy level available | `manual` only | `manual` / `assist` / `semi_auto` / `auto` | `manual` / `assist` / `semi_auto` / `auto` |
| Egress required | NO | NO | YES (to LLM provider) |
| Air-gapped friendly | ✓ | ✓ | ✗ (except Bedrock/Vertex in-VPC) |
| Recommended autonomy default | `manual` | `assist` | `assist` |

---

## 3. Tier resolution

> **The tier is resolved from the per-workspace LLM configuration (web UI), NOT from env.** There is no more `SUITEST_LLM_PROVIDER` / `SUITEST_LLM_API_KEY` / `SUITEST_LLM_MODEL` / `SUITEST_LLM_BASE_URL` / `SUITEST_EMBEDDINGS_BACKEND`. The provider is set in Settings → LLM provider, stored AES-encrypted in the DB (`LLMConfig`), and test-connected before save.

Two layers:

1. **Base (deployment-wide).** `packages/core/capabilities.py` is **always ZERO** and does not read env: `resolve_tier() → Tier.ZERO`, `resolve_embeddings() → disabled`. Called once at startup (`api` + `runner`), exposed via `GET /capabilities` as the base.
2. **Overlay (per-workspace).** `apps/api/.../capabilities.build_workspace_overlay` + `CapabilityService.resolve` read the workspace's active `LLMConfig` on every request and raise the effective tier via `_provider_to_tier`:

```python
LOCAL_PROVIDERS = {"ollama", "llamacpp", "vllm", "lmstudio"}

def _provider_to_tier(provider: str) -> Tier:
    p = provider.strip().lower()
    if p in {"", "none", "disabled"}:
        return Tier.ZERO
    if p in LOCAL_PROVIDERS:
        return Tier.LOCAL
    return Tier.CLOUD        # anthropic/openai/gemini/groq/openrouter/azure/bedrock/vertex/deepseek/mock
```

Validation (key required for non-IAM CLOUD, `base_url` required for LOCAL) happens at **save** time in `apps/api/.../services/llm_config_service.py` (`LLMConfigError`), not at resolve time — DB config is considered trusted. When a config is saved, `_refresh_capability` materializes `WorkspaceCapability`. Effective-tier flags are computed by the pure primitives `compute_features(tier, embeddings)` + `compute_autonomy(tier)` (still in `packages/core/capabilities.py`). Because the overlay reads the DB on every request, switching provider takes effect immediately — **without restart**.

> **The `mock` provider** returns canned deterministic responses from `packages/agent/providers/mock.py`; selected from the web UI for CI/dev without real API spend. It is classified as **CLOUD tier** by `_provider_to_tier` (full feature surface) but flagged `is_test_provider: true` in the `/capabilities` response so the UI renders a "Test provider — not for production" banner.

---

## 4. Per-feature gating policy

Every feature maps to `(required_tier, required_autonomy)`. The decorator `@require_capability(...)` is used at every entrypoint.

| Feature | Min tier | Min autonomy | Endpoint | Behavior below min |
|---------|----------|--------------|----------|-----------------------|
| Manual TCM CRUD | ZERO | manual | `/api/v1/cases/*` | always on |
| Run with `step.code` | ZERO | manual | `POST /api/v1/runs` (code-only steps) | always on |
| Deterministic generator (OpenAPI) | ZERO | manual | `POST /api/v1/generate/openapi` | always on |
| Deterministic generator (Recorder) | ZERO | manual | `POST /api/v1/generate/recorder` | always on |
| Deterministic generator (Crawler) | ZERO | manual | `POST /api/v1/generate/crawl` | always on |
| AI generation from PRD | LOCAL | assist | `POST /api/v1/agent/generate/cases` | `503 LLM_DISABLED` in ZERO |
| AI generation URL semantic | LOCAL | assist | `POST /api/v1/agent/generate/url-semantic` | `503 LLM_DISABLED` in ZERO |
| MCP tool discovery (LLM-assisted) | LOCAL | assist | `POST /api/v1/agent/generate/mcp-discover` | `503 LLM_DISABLED` in ZERO |
| Action→Code runtime translate | LOCAL | assist | (internal, runner) | step skipped with reason `NO_LLM_FOR_AGENTIC_STEP` in ZERO |
| AI diagnose run (`ai_diagnosis`) | LOCAL | assist | `POST /api/v1/runs/{id}/diagnose` | `503 LLM_DISABLED` in ZERO |
| AI auto-defect file (`auto_defect_filing_ai`) | LOCAL | assist | (auto, post-run) | rule-based fallback (`auto_defect_filing_rule`) in ZERO (see §9) |
| AI conversation panel (`ai_chat` / `ai_panel`) | LOCAL | assist | `POST /api/v1/chat` | `503 LLM_DISABLED` in ZERO; UI hides the panel (`ai_panel=false`) |
| Semantic search (`embeddings_semantic`) | ZERO* | manual | `GET /api/v1/search?semantic=1` | `409 EMBEDDINGS_DISABLED` if embeddings backend = `none` |
| FTS search | ZERO | manual | `GET /api/v1/search` | always on |
| Defect file (manual) | ZERO | manual | `POST /api/v1/defects` | always on |
| Defect file (auto, AI-reasoned) | LOCAL | assist | (auto) | rule-based fallback in ZERO |
| Semi-auto run gating | LOCAL | semi_auto | (autonomy) | requires both |
| Full-auto self-heal | LOCAL | auto | (autonomy, v1.x) | requires both |

\* Semantic search requires `embeddings.enabled = true`, independent of the LLM tier.

---

## 5. Embeddings tier (independent dial)

> **Status:** capability base embeddings = **disabled** (`resolve_embeddings()` ZERO-always; the `SUITEST_EMBEDDINGS_BACKEND` env has been removed). The `semantic_search` feature flag follows this base. The embedder **runtime** (`packages/core/embeddings.py::get_embedder`) still exists + separately (ZERO-tier feature). The matrix below = target design for when embeddings are exposed as a workspace dial (not yet); until then, all rows are effectively OFF.

Embeddings are a dial separate from the LLM tier. Matrix (target):

| LLM tier | Embeddings backend | Semantic search | RAG to LLM | Typical use case |
|----------|--------------------|-----------------|------------|------------------|
| ZERO | `none` | OFF (FTS only) | n/a | Pure air-gap, no AI needed |
| ZERO | `fastembed` | ON | n/a | Air-gap, needs smart search but no LLM |
| LOCAL | `none` | OFF | OFF | Local LLM without retrieval (small workspace) |
| LOCAL | `fastembed` | ON | ON (local-only) | **Recommended** air-gap with full AI |
| LOCAL | `openai`/`cohere` | ON | ON (mixed) | Local LLM + SaaS embeddings (compromise) |
| CLOUD | `none` | OFF | OFF | Cost-saving, no retrieval |
| CLOUD | `fastembed` | ON | ON | Privacy embeddings + paid LLM |
| CLOUD | `openai` | ON | ON | Default SaaS posture |
| CLOUD | `cohere` | ON | ON | Multilingual emphasis |

**Vector dimension** is determined when the Alembic migration first runs — the `document_chunk.embedding` column uses `Vector(dim)` matching the backend. Changing the backend post-deploy → re-embed required (admin tool `python -m packages.db.reembed --backend=...`).

---

## 6. Endpoint behavior in ZERO tier

### 6.1 Returns `503 LLM_DISABLED`

```json
{
  "error": "LLM_DISABLED",
  "message": "This endpoint requires LOCAL or CLOUD tier.",
  "current_tier": "ZERO",
  "required_tier": "LOCAL",
  "docs": "https://suitest.dev/docs/CAPABILITY_TIERS"
}
```

Endpoints that return this in ZERO:

- `POST /api/v1/agent/generate/cases`
- `POST /api/v1/agent/generate/url-semantic`
- `POST /api/v1/agent/generate/mcp-discover`
- `POST /api/v1/runs/{id}/diagnose`
- `POST /api/v1/chat`
- `POST /api/v1/agent/translate-step` (internal probe)

### 6.2 Works normally in ZERO

- `GET/POST/PATCH/DELETE /api/v1/cases/*`
- `GET/POST /api/v1/suites/*`
- `POST /api/v1/runs` — as long as every step has `step.code`
- `GET /api/v1/runs/{id}` + WS / SSE log stream
- `POST /api/v1/generate/openapi|recorder|crawl`
- `POST /api/v1/defects` (manual file)
- `GET /api/v1/search` (FTS)
- `GET /api/v1/search?semantic=1` — works only if `embeddings.enabled=true`
- `GET /api/v1/mcp/providers`, `POST /api/v1/mcp/providers`
- `GET /api/v1/integrations/*`
- `GET /capabilities`, `/health`, `/ready`, `/metrics`

### 6.3 Returns `400 STEPS_REQUIRE_CODE_IN_ZERO_LLM`

When the workspace setting `strict_zero_validation = true` (default) and the user POSTs a test case with a step whose `code` is empty:

```json
{
  "error": "STEPS_REQUIRE_CODE_IN_ZERO_LLM",
  "message": "Step 3 has no `code` and tier=ZERO has no LLM to translate actions at runtime.",
  "step_index": 3,
  "hint": "Either: (a) provide step.code, (b) record via browser recorder, or (c) upgrade tier."
}
```

---

## 7. Test case validation rules per tier

| Rule | ZERO + `strict_zero_validation=true` (default) | ZERO + strict=false | LOCAL / CLOUD |
|------|-----------------------------------------------|---------------------|---------------|
| Step must have `code` | ✓ enforced on save | not enforced; `executable=false` flagged | not enforced |
| Step `action` only allowed | ✗ | ✓ but `executable=false` | ✓ — `executable=true`, runner will translate |
| Can save test case w/ action-only steps | ✗ | ✓ (marked non-executable) | ✓ |
| Can run test case with non-executable step | n/a | ✗ pre-flight 400 | ✓ |
| `Step.executable` computed | `code IS NOT NULL` | `code IS NOT NULL` | `code IS NOT NULL OR action IS NOT NULL` |

The `strict_zero_validation` setting is set per workspace (default `true`). Use case for `false`: a team freshly migrating from TestRail wants to import 1000 action-only cases first, planning to convert / upgrade tier later.

---

## 8. Runner behavior per tier (decision tree)

Per step:

```
┌─ Step received from queue
│
├─ step.code present?
│   ├─ YES → execute deterministic via MCP (api-mcp / playwright-mcp / postgres-mcp / etc.)
│   │        ── outcome: pass | fail | error
│   │
│   └─ NO → check tier
│       ├─ tier == ZERO → SKIP step
│       │                  outcome: skipped
│       │                  reason: NO_LLM_FOR_AGENTIC_STEP
│       │                  run outcome: partial_skip
│       │
│       └─ tier in {LOCAL, CLOUD} → check autonomy
│           ├─ autonomy == manual → SKIP (unless user explicitly "run agentic")
│           │                       reason: AGENTIC_REQUIRES_ASSIST_OR_ABOVE
│           │
│           └─ autonomy >= assist → invoke LangGraph translate node
│               ├─ produces step.code at runtime → execute via MCP
│               │   ── outcome: pass | fail | error
│               │   ── record translated_code → audit log
│               │
│               └─ translate fails → outcome: error
│                                     reason: TRANSLATE_FAILED
```

Aggregate run outcome:

- All steps pass → `pass`
- Any step fail → `fail`
- Any step error → `error`
- Any step skipped + no fail/error → `partial_skip`

`partial_skip` in the ZERO tier is considered **expected** when a case has action-only steps — the UI shows an "Upgrade tier to run this step" banner instead of red.

---

## 9. Diagnosis fallback in ZERO

When a run fails and tier=ZERO, there is no AI narration. Instead:

**Rule-based defect filing:**

1. Capture failed step + artifact + assertion delta (expected vs actual).
2. Compute defect title via template: `[{tag}] {case.title} — step {idx} {assertion_kind} failed`.
3. Severity inferred from the case tag/priority (P0 → blocker, P1 → critical, etc.).
4. Body: structured (step desc, expected, actual, artifact link, run id). **No prose root-cause.**
5. Tag `[manual-triage]` added → flag for human review.
6. File to the tracker integration per the workspace setting.

When the tier is upgraded to LOCAL/CLOUD, old runs keep their rule-based defects; users can hit `POST /api/v1/runs/{id}/diagnose` to regenerate with AI narration.

---

## 10. Capability endpoint contract

`GET /capabilities` — public, no auth required (the UI fetches it before the login screen).

Response example (CLOUD tier + openai embeddings):

```json
{
  "tier": "CLOUD",
  "llm": {
    "provider": "anthropic",
    "model": "claude-sonnet-4-5",
    "base_url": null,
    "is_test_provider": false
  },
  "embeddings": {
    "enabled": true,
    "backend": "openai",
    "model": "text-embedding-3-small",
    "dim": 1536
  },
  "features": {
    "manual_tcm": true,
    "deterministic_runner": true,
    "deterministic_generator_openapi": true,
    "deterministic_generator_recorder": true,
    "deterministic_generator_crawler": true,
    "ai_generation": true,
    "ai_execution_agentic": true,
    "ai_diagnosis": true,
    "ai_translation": true,
    "ai_chat": true,
    "ai_panel": true,
    "embeddings_semantic": true,
    "fts_search": true,
    "autonomy_assist": true,
    "autonomy_semi_auto": true,
    "autonomy_auto": true,
    "auto_defect_filing_ai": true,
    "auto_defect_filing_rule": true
  },
  "autonomy": {
    "available": ["manual", "assist", "semi_auto", "auto"],
    "default": "assist"
  },
  "mcpProviders": [
    { "id": "mcp_aaa", "name": "playwright-mcp", "kind": "playwright", "health": "healthy", "isDefault": true },
    { "id": "mcp_bbb", "name": "api-mcp",        "kind": "api",        "health": "healthy", "isDefault": true },
    { "id": "mcp_ccc", "name": "postgres-mcp",   "kind": "postgres",   "health": "unknown", "isDefault": false }
  ],
  "version": "1.0.0"
}
```

ZERO tier response:

```json
{
  "tier": "ZERO",
  "llm": { "provider": "none", "model": null, "base_url": null, "is_test_provider": false },
  "embeddings": { "enabled": false, "backend": "none" },
  "features": {
    "manual_tcm": true,
    "deterministic_runner": true,
    "deterministic_generator_openapi": true,
    "deterministic_generator_recorder": true,
    "deterministic_generator_crawler": true,
    "ai_generation": false,
    "ai_execution_agentic": false,
    "ai_diagnosis": false,
    "ai_translation": false,
    "ai_chat": false,
    "ai_panel": false,
    "embeddings_semantic": false,
    "fts_search": true,
    "autonomy_assist": false,
    "autonomy_semi_auto": false,
    "autonomy_auto": false,
    "auto_defect_filing_ai": false,
    "auto_defect_filing_rule": true
  },
  "autonomy": {
    "available": ["manual"],
    "default": "manual"
  },
  "mcpProviders": [
    { "id": "mcp_aaa", "name": "playwright-mcp", "kind": "playwright", "health": "unknown", "isDefault": true },
    { "id": "mcp_bbb", "name": "api-mcp",        "kind": "api",        "health": "unknown", "isDefault": true }
  ],
  "version": "1.0.0"
}
```

> `mcpProviders[]` items shape: `{id, name, kind, health, isDefault}` — same as the field returned by `GET /mcp/providers`. `isDefault` is true when this provider is the default for at least one `target_kind` per `/mcp/routing`. Cross-ref: [API.md § 3.0](./API.md#30-capabilities-public).

The frontend uses this response to render `<Gated feature="ai_generation">…</Gated>` and the tier badge in the topbar.

---

## 11. Upgrading tier at runtime

One path: **Settings → LLM page (per-workspace, DB-stored)**. There is no env path anymore.

1. An admin user opens Settings → LLM (`apps/web/.../components/settings/LlmSettingsPanel.tsx`).
2. Picks a provider, enters model + API key (write-only field) / base_url (for LOCAL).
3. Clicks "Test connection" → `POST /workspaces/{id}/llm-config/test` (LiteLLM check-connect) before save is allowed.
4. Save → `PUT /workspaces/{id}/llm-config` → `LLMConfig` row (api_key AES-GCM-encrypted with `SUITEST_ENCRYPTION_KEY`); `llm_config_service._refresh_capability` materializes `WorkspaceCapability`.
5. The effective tier takes effect immediately: `GET /capabilities` (the overlay reads the DB on every request) reflects the new tier **without restart**; existing action-only test cases become `executable=true`.

Precedence: workspace `LLMConfig` > `WorkspaceCapability` > ZERO base. Audit log entry recorded.

---

## 12. Cost & quota guardrails per tier

| Tier | Concern | Default guardrail | Override |
|------|---------|-------------------|----------|
| ZERO | n/a | — | — |
| LOCAL | GPU contention / OOM | concurrent agent sessions per worker = 2 | `SUITEST_LOCAL_MAX_CONCURRENT` |
| CLOUD | $$$ cost | per-workspace daily cap (default $50) → block new AI requests with `429 BUDGET_EXCEEDED` | `LLMConfig.daily_cap_usd` |
| CLOUD | rate-limit upstream | LiteLLM retry w/ exponential backoff, fallback model (if set) | `LLMConfig.fallback_model` |

Cost is computed via `litellm.completion_cost()` → accumulated into `AgentSession.cost_usd` and the `Insights → Cost` dashboard. Full budget guard: v1.x.

---

## 13. Decision matrix — "Which tier do I need?"

| I want to... | Minimum tier | Notes |
|---------------|-------------|---------|
| Replace TestRail (manual TCM only) | ZERO | + deterministic runner bonus |
| Replace Playwright (deterministic runner) | ZERO | step.code mode, MCP playwright |
| Import OpenAPI spec → generate contract tests | ZERO | deterministic generator |
| Record manual session → generate Playwright test | ZERO | browser recorder |
| Crawl URL, generate skeleton smoke suite | ZERO | heuristic crawler |
| Search test cases by meaning ("checkout flow") | ZERO + `fastembed` | embeddings do not need an LLM |
| Generate test cases from a natural-language PRD | LOCAL or CLOUD | needs an LLM |
| Agent runs tests that only have actions ("click the login button") | LOCAL or CLOUD | runtime translate |
| AI narrates why a test failed | LOCAL or CLOUD | diagnose endpoint |
| Auto-categorize failure (FLAKE / REGRESSION / DEFECT) + auto-rerun | LOCAL or CLOUD + autonomy ≥ `semi_auto` | combined gate |
| Auto-file defect with root-cause prose | LOCAL or CLOUD + autonomy ≥ `assist` | rule-based still works in ZERO |
| Air-gapped, no egress, full AI | LOCAL + `fastembed` | enterprise privacy recommendation |
| Air-gapped, no egress, no AI | ZERO | "TestRail+Playwright in 1 product" mode |
| Try Suitest in 5 minutes | ZERO | docker compose up |
| Production multi-tenant SaaS posture | CLOUD | Helm + budget guard |

---

## 14. Implementation references

- Resolver: `packages/core/capabilities.py`
- Decorator: `packages/core/gating.py` — `@require_capability(feature=...)`, `@require_tier(min=...)`, `@require_autonomy(min=...)`
- DB model: `packages/db/models/llm_config.py`, `packages/db/models/workspace_capability.py`
- Endpoint: `apps/api/routes/capabilities.py`
- Frontend hook: `apps/web/src/lib/use-capabilities.ts` (Zustand store backed by `/capabilities` fetch)
- UI gate: `apps/web/src/components/shared/Gated.tsx`

---

## 15. Cross-references

- Services architecture → [ARCHITECTURE.md](./ARCHITECTURE.md)
- Deployment per tier → [DEPLOYMENT.md](./DEPLOYMENT.md)
- Autonomy levels → [AUTONOMY.md](./AUTONOMY.md)
- MCP plugins → [MCP_PLUGINS.md](./MCP_PLUGINS.md)
