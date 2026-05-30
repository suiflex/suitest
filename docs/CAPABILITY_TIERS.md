# docs/CAPABILITY_TIERS.md

> Spec lengkap capability tiering Suitest: **ZERO / LOCAL / CLOUD**. Dipakai sebagai kontrak antara `packages/core/capabilities.py` (resolver), `apps/api` (endpoint gating), `apps/runner` (step execution), dan `apps/web` (UI gating). Untuk arsitektur baca [ARCHITECTURE.md](./ARCHITECTURE.md). Untuk deployment baca [DEPLOYMENT.md](./DEPLOYMENT.md). Design rationale: [design memo](./superpowers/specs/2026-05-26-suitest-oss-pivot-design.md).

---

## 1. Konsep

Suitest harus jalan di tiga "modus operandi":

1. **Self-host air-gapped, no LLM.** Tim QA enterprise / regulated industries yang ngga boleh egress ke cloud. Suitest masih harus 100% berguna sebagai TCM + deterministic runner.
2. **Self-host with local LLM.** Tim yang punya GPU di-prem (Ollama / vLLM / llama.cpp). Privacy preserved, AI features aktif.
3. **Self-host + cloud LLM (BYO).** Tim yang punya budget API SaaS — bawa key sendiri (Anthropic / OpenAI / Gemini / dst). Fitur full.

Karenanya tier **bukan** pricing tier, melainkan **capability matrix** yang ditentukan oleh env config. Sama binary, beda surface area.

Prinsip:

- **Default = ZERO.** Boot pertama harus jalan tanpa konfigurasi tambahan.
- **Upgrade = set env.** Switching tier = edit env + restart, no rebuild.
- **No silent degradation.** Kalau fitur tidak available di tier ini, endpoint return `503 LLM_DISABLED` dengan reason — UI gate dengan tooltip.
- **Embeddings tier independent.** Bisa ZERO LLM + `fastembed` embeddings = tetap dapet semantic search.

---

## 2. Tier definition

| Aspek | ZERO | LOCAL | CLOUD |
|-------|------|-------|-------|
| Trigger env (`SUITEST_LLM_PROVIDER`) | `none` / unset | `ollama` / `llamacpp` / `vllm` / `lmstudio` | `anthropic` / `openai` / `gemini` / `groq` / `openrouter` / `azure` / `bedrock` / `vertex` / `deepseek` / `mock` (test/dev only — see §3) |
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
| Embeddings (`SUITEST_EMBEDDINGS_BACKEND`) | opt-in via `fastembed` | opt-in any | opt-in any |
| Semantic search | only if embeddings on | ✓ if embeddings on | ✓ if embeddings on |
| FTS fallback search | ✓ (always) | ✓ | ✓ |
| Autonomy level available | `manual` only | `manual` / `assist` / `semi_auto` / `auto` | `manual` / `assist` / `semi_auto` / `auto` |
| Egress required | NO | NO | YES (to LLM provider) |
| Air-gapped friendly | ✓ | ✓ | ✗ (kecuali Bedrock/Vertex in-VPC) |
| Recommended autonomy default | `manual` | `assist` | `assist` |

---

## 3. Tier resolution algorithm

Implementasi di `packages/core/capabilities.py`. Dipanggil sekali saat process startup (`api` + `runner`), hasil di-cache immutable, expose via `GET /capabilities`.

Pseudocode:

```python
LOCAL_PROVIDERS = {"ollama", "llamacpp", "vllm", "lmstudio"}
CLOUD_PROVIDERS = {
    "anthropic", "openai", "gemini", "groq", "openrouter",
    "azure", "bedrock", "vertex", "deepseek",
    "mock",   # test/dev only — canned deterministic responses, CI uses this to avoid real API spend
}

def resolve_tier() -> Tier:
    provider = (os.getenv("SUITEST_LLM_PROVIDER") or "none").lower().strip()

    if provider in {"", "none", "disabled"}:
        return Tier.ZERO

    if provider in LOCAL_PROVIDERS:
        # base_url required untuk local (no default cluster DNS guess)
        if not os.getenv("SUITEST_LLM_BASE_URL"):
            raise ConfigError("LOCAL tier butuh SUITEST_LLM_BASE_URL")
        return Tier.LOCAL

    if provider in CLOUD_PROVIDERS:
        # bedrock/vertex pakai IAM, mock = no creds, lainnya butuh API key
        if provider not in {"bedrock", "vertex", "mock"} and not os.getenv("SUITEST_LLM_API_KEY"):
            raise ConfigError(f"CLOUD provider {provider} butuh SUITEST_LLM_API_KEY")
        return Tier.CLOUD

    raise ConfigError(f"Unknown SUITEST_LLM_PROVIDER: {provider}")


def resolve_embeddings() -> EmbeddingsConfig:
    backend = (os.getenv("SUITEST_EMBEDDINGS_BACKEND") or "none").lower()
    if backend == "none":
        return EmbeddingsConfig(enabled=False)
    if backend == "fastembed":
        return EmbeddingsConfig(enabled=True, backend="fastembed",
                                model=os.getenv("SUITEST_EMBEDDINGS_MODEL", "BAAI/bge-small-en-v1.5"),
                                dim=384)
    if backend == "openai":
        return EmbeddingsConfig(enabled=True, backend="openai",
                                model=os.getenv("SUITEST_EMBEDDINGS_MODEL", "text-embedding-3-small"),
                                dim=1536)
    if backend == "cohere":
        return EmbeddingsConfig(enabled=True, backend="cohere",
                                model=os.getenv("SUITEST_EMBEDDINGS_MODEL", "embed-english-v3.0"),
                                dim=1024)
    raise ConfigError(f"Unknown SUITEST_EMBEDDINGS_BACKEND: {backend}")
```

**Catatan penting**: workspace-level DB-stored `LLMConfig` override env hanya **setelah** process re-init (mis. user set provider via Settings → LLM page → trigger graceful restart / signal). Tidak ada hot-swap mid-process untuk hindari surprise.

> **`mock` provider** returns canned deterministic responses from `packages/agent/providers/mock.py`; used in CI to avoid real API spend and in local dev when `SUITEST_LLM_PROVIDER=mock`. Treated as **CLOUD tier** for capability semantics (full feature surface) but flagged `is_test_provider: true` in the `/capabilities` response so the UI can render a "Test provider — not for production" banner. Not listed in [DEPLOYMENT.md §5 tier matrix](./DEPLOYMENT.md#5-tier-specific-environment-matrix) because it is not a deployable provider.

---

## 4. Per-feature gating policy

Setiap fitur memetakan ke `(required_tier, required_autonomy)`. Decorator `@require_capability(...)` dipakai di setiap entrypoint.

| Feature | Min tier | Min autonomy | Endpoint | Behavior di bawah min |
|---------|----------|--------------|----------|-----------------------|
| Manual TCM CRUD | ZERO | manual | `/api/v1/cases/*` | always on |
| Run with `step.code` | ZERO | manual | `POST /api/v1/runs` (code-only steps) | always on |
| Deterministic generator (OpenAPI) | ZERO | manual | `POST /api/v1/generate/openapi` | always on |
| Deterministic generator (Recorder) | ZERO | manual | `POST /api/v1/generate/recorder` | always on |
| Deterministic generator (Crawler) | ZERO | manual | `POST /api/v1/generate/crawl` | always on |
| AI generation from PRD | LOCAL | assist | `POST /api/v1/agent/generate/cases` | `503 LLM_DISABLED` di ZERO |
| AI generation URL semantic | LOCAL | assist | `POST /api/v1/agent/generate/url-semantic` | `503 LLM_DISABLED` di ZERO |
| MCP tool discovery (LLM-assisted) | LOCAL | assist | `POST /api/v1/agent/generate/mcp-discover` | `503 LLM_DISABLED` di ZERO |
| Action→Code runtime translate | LOCAL | assist | (internal, runner) | step skipped dgn reason `NO_LLM_FOR_AGENTIC_STEP` di ZERO |
| AI diagnose run (`ai_diagnosis`) | LOCAL | assist | `POST /api/v1/runs/{id}/diagnose` | `503 LLM_DISABLED` di ZERO |
| AI auto-defect file (`auto_defect_filing_ai`) | LOCAL | assist | (auto, post-run) | rule-based fallback (`auto_defect_filing_rule`) di ZERO (lihat §9) |
| AI conversation panel (`ai_chat` / `ai_panel`) | LOCAL | assist | `POST /api/v1/chat` | `503 LLM_DISABLED` di ZERO; UI hide panel (`ai_panel=false`) |
| Semantic search (`embeddings_semantic`) | ZERO* | manual | `GET /api/v1/search?semantic=1` | `409 EMBEDDINGS_DISABLED` kalau embeddings backend = `none` |
| FTS search | ZERO | manual | `GET /api/v1/search` | always on |
| Defect file (manual) | ZERO | manual | `POST /api/v1/defects` | always on |
| Defect file (auto, AI-reasoned) | LOCAL | assist | (auto) | rule-based fallback di ZERO |
| Semi-auto run gating | LOCAL | semi_auto | (autonomy) | requires both |
| Full-auto self-heal | LOCAL | auto | (autonomy, v1.x) | requires both |

\* Semantic search butuh `embeddings.enabled = true`, independen dari LLM tier.

---

## 5. Embeddings tier (independent dial)

`SUITEST_EMBEDDINGS_BACKEND` adalah dial terpisah. Matrix:

| LLM tier | Embeddings backend | Semantic search | RAG ke LLM | Tipikal use case |
|----------|--------------------|-----------------|------------|------------------|
| ZERO | `none` | OFF (FTS only) | n/a | Air-gap pure, ngga butuh AI |
| ZERO | `fastembed` | ON | n/a | Air-gap, butuh smart search tapi no LLM |
| LOCAL | `none` | OFF | OFF | Local LLM tanpa retrieval (small workspace) |
| LOCAL | `fastembed` | ON | ON (local-only) | **Recommended** air-gap dgn AI penuh |
| LOCAL | `openai`/`cohere` | ON | ON (mixed) | LLM local + embeddings SaaS (kompromi) |
| CLOUD | `none` | OFF | OFF | Cost-saving, no retrieval |
| CLOUD | `fastembed` | ON | ON | Privacy embeddings + paid LLM |
| CLOUD | `openai` | ON | ON | Default SaaS posture |
| CLOUD | `cohere` | ON | ON | Multilingual emphasis |

**Vector dimension** ditentukan saat Alembic migration jalan pertama kali — kolom `document_chunk.embedding` pakai `Vector(dim)` sesuai backend. Ganti backend post-deploy → re-embed required (admin tool `python -m packages.db.reembed --backend=...`).

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

Endpoints yang return ini di ZERO:

- `POST /api/v1/agent/generate/cases`
- `POST /api/v1/agent/generate/url-semantic`
- `POST /api/v1/agent/generate/mcp-discover`
- `POST /api/v1/runs/{id}/diagnose`
- `POST /api/v1/chat`
- `POST /api/v1/agent/translate-step` (internal probe)

### 6.2 Works normally in ZERO

- `GET/POST/PATCH/DELETE /api/v1/cases/*`
- `GET/POST /api/v1/suites/*`
- `POST /api/v1/runs` — selama semua step punya `step.code`
- `GET /api/v1/runs/{id}` + WS / SSE log stream
- `POST /api/v1/generate/openapi|recorder|crawl`
- `POST /api/v1/defects` (manual file)
- `GET /api/v1/search` (FTS)
- `GET /api/v1/search?semantic=1` — works only if `embeddings.enabled=true`
- `GET /api/v1/mcp/providers`, `POST /api/v1/mcp/providers`
- `GET /api/v1/integrations/*`
- `GET /capabilities`, `/health`, `/ready`, `/metrics`

### 6.3 Returns `400 STEPS_REQUIRE_CODE_IN_ZERO_LLM`

Bila workspace setting `strict_zero_validation = true` (default) dan user POST test case dgn step yang `code` kosong:

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

Setting `strict_zero_validation` di-set per workspace (default `true`). Use case `false`: tim baru migrate dari TestRail, mau import 1000 case action-only dulu, plan to convert / upgrade tier later.

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
│           ├─ autonomy == manual → SKIP (kecuali user explicit "run agentic")
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

Outcome run aggregate:

- All steps pass → `pass`
- Any step fail → `fail`
- Any step error → `error`
- Any step skipped + no fail/error → `partial_skip`

`partial_skip` di ZERO tier dianggap **expected** kalau case punya action-only step — UI tampil banner "Upgrade tier untuk jalankan step ini" instead of red.

---

## 9. Diagnosis fallback di ZERO

Saat run gagal dan tier=ZERO, tidak ada AI narration. Sebagai gantinya:

**Rule-based defect filing:**

1. Capture failed step + artifact + assertion delta (expected vs actual).
2. Compute defect title via template: `[{tag}] {case.title} — step {idx} {assertion_kind} failed`.
3. Severity inferred dari case tag/priority (P0 → blocker, P1 → critical, dst.).
4. Body: structured (step desc, expected, actual, artifact link, run id). **No prose root-cause.**
5. Tag `[manual-triage]` ditambah → flag untuk human review.
6. File ke tracker integration sesuai workspace setting.

Saat tier upgrade ke LOCAL/CLOUD, run lama tetap punya defect rule-based; user bisa hit `POST /api/v1/runs/{id}/diagnose` untuk regenerate dgn AI narration.

---

## 10. Capability endpoint contract

`GET /capabilities` — public, no auth required (UI fetch sebelum login screen).

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

Frontend pakai response ini untuk render `<Gated feature="ai_generation">…</Gated>` dan tier badge di topbar.

---

## 11. Upgrading tier at runtime

Dua jalan:

### 11.1 Via env (compose / Helm)

1. Edit `.env` atau `values.yaml` — set `SUITEST_LLM_PROVIDER`, key, model.
2. Restart `api` + `runner` (`docker compose restart api runner` / Helm `rollout restart`).
3. `GET /capabilities` reflect tier baru.
4. Existing test case action-only langsung jadi `executable=true`.

### 11.2 Via Settings → LLM page (DB-stored config)

1. Admin user buka Settings → LLM.
2. Pilih provider, masukin API key (write-only field).
3. Click "Test connection" → backend call LiteLLM `health_check()` against provider.
4. Save → `LLMConfig` row inserted (api_key di-AES-GCM-encrypt dgn `SUITEST_ENCRYPTION_KEY`).
5. Backend emit `config_reload` event → graceful restart marker → next request schedule worker recycle.
6. Tier badge update setelah recycle complete.

DB config **override** env (precedence: workspace `LLMConfig` > env). Audit log entry recorded.

---

## 12. Cost & quota guardrails per tier

| Tier | Concern | Default guardrail | Override |
|------|---------|-------------------|----------|
| ZERO | n/a | — | — |
| LOCAL | GPU contention / OOM | concurrent agent sessions per worker = 2 | `SUITEST_LOCAL_MAX_CONCURRENT` |
| CLOUD | $$$ cost | per-workspace daily cap (default $50) → block new AI request dgn `429 BUDGET_EXCEEDED` | `LLMConfig.daily_cap_usd` |
| CLOUD | rate-limit upstream | LiteLLM retry w/ exponential backoff, fallback model (jika diset) | `LLMConfig.fallback_model` |

Cost dihitung via `litellm.completion_cost()` → diakumulasi ke `AgentSession.cost_usd` dan dashboard `Insights → Cost`. Budget guard penuh: v1.x.

---

## 13. Decision matrix — "Which tier do I need?"

| Saya ingin... | Minimum tier | Catatan |
|---------------|-------------|---------|
| Replace TestRail (manual TCM only) | ZERO | + deterministic runner bonus |
| Replace Playwright (deterministic runner) | ZERO | step.code mode, MCP playwright |
| Import OpenAPI spec → generate contract tests | ZERO | deterministic generator |
| Record manual session → generate Playwright test | ZERO | browser recorder |
| Crawl URL, generate skeleton smoke suite | ZERO | heuristic crawler |
| Search test cases by meaning ("checkout flow") | ZERO + `fastembed` | embeddings ngga butuh LLM |
| Generate test cases dari PRD natural language | LOCAL or CLOUD | butuh LLM |
| Agen jalanin test cuma punya action ("klik tombol login") | LOCAL or CLOUD | runtime translate |
| AI narasikan kenapa test gagal | LOCAL or CLOUD | diagnose endpoint |
| Auto-categorize failure (FLAKE / REGRESSION / DEFECT) + auto-rerun | LOCAL or CLOUD + autonomy ≥ `semi_auto` | combined gate |
| Auto-file defect dgn root-cause prose | LOCAL or CLOUD + autonomy ≥ `assist` | rule-based di ZERO tetap jalan |
| Air-gapped, no egress, full AI | LOCAL + `fastembed` | rekomendasi enterprise privacy |
| Air-gapped, no egress, no AI | ZERO | "TestRail+Playwright in 1 product" mode |
| Coba Suitest 5 menit | ZERO | docker compose up |
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

## 15. Referensi silang

- Arsitektur services → [ARCHITECTURE.md](./ARCHITECTURE.md)
- Deployment per tier → [DEPLOYMENT.md](./DEPLOYMENT.md)
- Autonomy levels → [AUTONOMY.md](./AUTONOMY.md)
- MCP plugins → [MCP_PLUGINS.md](./MCP_PLUGINS.md)
- Design memo → [design memo](./superpowers/specs/2026-05-26-suitest-oss-pivot-design.md)
