# docs/AI_AGENT.md

> Arsitektur, prompts, dan tools untuk Suitest Agent. Setelah pivot OSS (memo 2026-05-26), stack agen pindah dari Anthropic-only TypeScript SDK ke **Python 3.12 + LiteLLM (multi-provider) + LangGraph (state machine)**. Semua LLM call lewat `packages/agent/` — **tidak boleh** call provider SDK langsung dari `apps/api` atau `apps/web`.

> 🚧 **SPEC — targets M3 (CLOUD LLM tier). NOT built on current tree.** `packages/agent` is stubs only (no LiteLLM, no LangGraph, no tools/prompts/graphs). Track in [ROADMAP.md](./ROADMAP.md) M3.
>
> Cross-refs: [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md), [AUTONOMY.md](./AUTONOMY.md), [GENERATORS.md](./GENERATORS.md), [MCP_PLUGINS.md](./MCP_PLUGINS.md), [DATA_MODEL.md](./DATA_MODEL.md), [API.md](./API.md), [ROADMAP.md](./ROADMAP.md).

---

## 1. Goal & 4 agent modes

Suitest Agent adalah layer Python yg meng-orchestrate LLM untuk 4 mode operasi (mapping ke enum `AgentSessionKind`). Setiap mode tier-aware: di ZERO tier semua mode return error `LLM_DISABLED` (HTTP 503) dengan hint ke deterministic alternative.

| Mode | Tujuan | Default model class | ZERO tier behavior |
|------|--------|---------------------|--------------------|
| **GENERATION** | Generate test cases dari PRD / URL semantic / MCP discovery / OpenAPI-enrich | reasoning (Sonnet-class / GPT-4o-class / Llama 3.1 70B local) | 503 → hint: pakai `/generators/openapi`, `/generators/recorder`, `/generators/crawler` |
| **EXECUTION** | Translate `step.action` (English) ke MCP calls runtime; drive agentic flow | reasoning | 503 → hint: semua step harus punya `step.code` di ZERO; bisa di-relax via `workspace.strict_zero=false` (step di-skip dgn warning) |
| **DIAGNOSIS** | Analisis root cause defect post-run | reasoning | 503 → fallback rule-based categorizer (assertion regex → `MANUAL_TRIAGE`) |
| **CONVERSATION** | Chat di AI panel UI, query state, jawab pertanyaan | small/fast (Haiku-class / GPT-4o-mini / Llama 3.1 8B) | 503 → AI panel hidden di UI |

Tier-aware response example saat tier=ZERO:

```json
HTTP 503
{
  "code": "LLM_DISABLED",
  "message": "AI features require LLM provider configuration.",
  "hint": "Use deterministic generators (POST /generators/openapi) or manual TCM workflow.",
  "docs_url": "https://docs.suitest.dev/capability-tiers"
}
```

Model selection per session: agen pilih model dari `LLMConfig.preferred_models` (per-task mapping) → LiteLLM router. Conversation mode auto-downgrade ke smallest model. Override per request via `model_hint` di `POST /agent/*`.

---

## 2. Package layout

```
packages/agent/
├── pyproject.toml
├── suitest_agent/
│   ├── __init__.py
│   ├── capabilities.py              # tier + autonomy gate (require_tier, require_autonomy)
│   ├── providers/
│   │   ├── litellm_router.py        # LiteLLM init, model registry, cost calc
│   │   ├── ollama.py                # local provider config (base_url, model pull check)
│   │   └── mock.py                  # deterministic provider for tests + dev
│   ├── sessions/
│   │   ├── manager.py               # AgentSession lifecycle, persistence (SQLAlchemy async)
│   │   └── streaming.py             # LiteLLM stream → Suitest event bridge (SSE/WS via FastAPI)
│   ├── tasks/
│   │   ├── generation.py            # GENERATION mode entrypoint
│   │   ├── execution.py             # EXECUTION mode entrypoint
│   │   ├── diagnosis.py             # DIAGNOSIS mode entrypoint
│   │   └── conversation.py          # CONVERSATION mode entrypoint
│   ├── graphs/                      # LangGraph definitions per scenario
│   │   ├── generate_from_prd.py
│   │   ├── generate_from_openapi_ai.py   # AI-enrich on top of deterministic
│   │   ├── generate_from_url_semantic.py
│   │   ├── execute_run.py
│   │   └── diagnose.py
│   ├── tools/
│   │   ├── registry.py              # all tools, tier-filtered + autonomy-filtered
│   │   ├── docs.py                  # docs.read, docs.list_endpoints
│   │   ├── code.py                  # code.read via GitHub App / local repo
│   │   ├── mcp.py                   # mcp.invoke, mcp.discover_tools, mcp.invoke_typed
│   │   ├── db.py                    # db.query_cases / query_runs / query_defects
│   │   ├── target.py                # target.classify (deterministic, no LLM)
│   │   ├── export.py                # case.export → Playwright/Cypress/Selenium
│   │   └── tracker.py               # Jira / Linear / GitHub Issues
│   ├── prompts/
│   │   ├── v1/
│   │   │   ├── system-base.md
│   │   │   ├── generate-from-prd.md
│   │   │   ├── generate-from-openapi-enrich.md
│   │   │   ├── generate-from-url-semantic.md
│   │   │   ├── execute-run.md
│   │   │   ├── diagnose.md
│   │   │   └── conversation.md
│   │   └── loader.py                # versioned, content-hash-pinned
│   ├── rag/
│   │   ├── embeddings.py            # backend dispatcher (none / fastembed / openai / cohere)
│   │   ├── retriever.py             # pgvector semantic + Postgres FTS fallback
│   │   └── chunker.py               # markdown-aware, code-fence-aware
│   ├── eval/
│   │   ├── runner.py                # eval harness CLI (`python -m suitest_agent.eval`)
│   │   └── fixtures/                # golden datasets (PRDs, OpenAPI, failed runs)
│   └── observability/
│       ├── tracing.py               # OpenTelemetry spans + attributes
│       └── langfuse.py              # optional Langfuse self-host integration
└── tests/
    ├── test_capabilities.py
    ├── test_graphs/
    ├── test_tools/
    └── snapshots/                   # deterministic mock provider output
```

`pyproject.toml` excerpt:

```toml
[project]
name = "suitest-agent"
requires-python = ">=3.12"
dependencies = [
  "litellm>=1.50",
  "langgraph>=0.2",
  "langgraph-checkpoint-postgres>=2.0",
  "pydantic>=2.7",
  "sqlalchemy[asyncio]>=2.0",
  "asyncpg>=0.29",
  "pgvector>=0.3",
  "mcp>=1.0",
  "opentelemetry-api>=1.27",
  "opentelemetry-sdk>=1.27",
  "structlog>=24.1",
]

[project.optional-dependencies]
embeddings-local = ["fastembed>=0.3"]
observability = ["langfuse>=2.0"]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "respx>=0.21"]
```

---

## 3. LiteLLM integration

`providers/litellm_router.py` adalah satu-satunya tempat yg memanggil LiteLLM. Semua mode dispatch lewat fungsi `complete()` / `stream_complete()`.

```python
from __future__ import annotations
import litellm
from litellm import acompletion, completion_cost
from litellm.caching import Cache
from pydantic import BaseModel

class ModelCall(BaseModel):
    model: str          # LiteLLM model id, e.g. "anthropic/claude-sonnet-4-5"
    messages: list[dict]
    temperature: float = 0.2
    max_tokens: int = 4096
    tools: list[dict] | None = None
    cache_control: bool = True   # enable Anthropic prompt caching headers when supported
    seed: int | None = None

# Configure once on startup
litellm.cache = Cache(type="redis", host="redis", port=6379, ttl=3600)
litellm.set_verbose = False
litellm.drop_params = True     # silently drop provider-unsupported params (e.g. seed for Anthropic)

async def stream_complete(call: ModelCall):
    """Single entrypoint; yields normalized chunks."""
    response = await acompletion(
        model=call.model,
        messages=call.messages,
        temperature=call.temperature,
        max_tokens=call.max_tokens,
        tools=call.tools,
        stream=True,
        seed=call.seed,
    )
    async for chunk in response:
        yield chunk

def cost_usd(response) -> float:
    """Calculated post-call from response usage."""
    return completion_cost(completion_response=response)
```

### Provider mapping

| Suitest provider name | LiteLLM backing | Notes |
|-----------------------|-----------------|-------|
| `anthropic` | `anthropic/claude-*` | Prompt caching via `cache_control: {type: "ephemeral"}` header on system + RAG blocks. Tool use native. |
| `openai` | `openai/gpt-*` | Tool use native. JSON mode for structured output. |
| `gemini` | `gemini/gemini-*` | Google AI Studio key. Tool use native. |
| `groq` | `groq/llama-*` | Cheap + fast. Limited context (32k). Good for CONVERSATION. |
| `openrouter` | `openrouter/<model>` | Single key, 200+ models. Cost premium ~5%. |
| `azure` | `azure/<deployment>` | Requires `AZURE_API_BASE`, `AZURE_API_KEY`, `AZURE_API_VERSION`. Per-deployment routing. |
| `bedrock` | `bedrock/<model>` | Requires AWS creds (`AWS_ACCESS_KEY_ID` etc.) or IAM role. Region-specific model availability. |
| `vertex` | `vertex_ai/<model>` | Requires GCP SA JSON via `GOOGLE_APPLICATION_CREDENTIALS`. Project + location config. |
| `deepseek` | `deepseek/deepseek-*` | Cheap reasoning. OpenAI-compatible API shape. |
| `ollama` | `ollama/<model>` | LOCAL tier. `OLLAMA_API_BASE=http://ollama:11434`. Tool use via `ollama/llama3.1` etc. |
| `llamacpp` | `openai/<any>` w/ `api_base` | LOCAL tier. llama.cpp server with OpenAI shim. |
| `vllm` | `openai/<any>` w/ `api_base` | LOCAL tier, GPU. OpenAI-compatible. |
| `lmstudio` | `openai/<any>` w/ `api_base` | LOCAL tier, desktop. OpenAI-compatible. |

Resolution: `LLMConfig.provider` (string) + `LLMConfig.api_key` (AES-GCM) + optional `LLMConfig.api_base` → LiteLLM env vars set at process start by `providers/litellm_router.init_from_config()`.

---

## 4. LangGraph state machines

Setiap mode dijalankan sebagai LangGraph `StateGraph`. State dipersist via `langgraph-checkpoint-postgres` → resumable session (penting untuk long-running generation & runs).

### 4.1 GENERATION (from PRD)

```
classify_input
   ↓
chunk_input ──→ retrieve_rag ──→ search_existing_suite
                                       ↓
                              for_each_story (Send API fan-out)
                                       ↓
                  ┌────────────────────┼─────────────────────┐
                  ↓                    ↓                     ↓
            draft_happy          draft_edges           score_priority
                  ↓                    ↓                     ↓
                  └────────────────────┴─────────────────────┘
                                       ↓
                                 stream_emit          (SSE per case)
                                       ↓
                                persist_drafts        (DRAFT status)
                                       ↓
                                     END
```

Node responsibilities (Python):

```python
from langgraph.graph import StateGraph, END, Send
from pydantic import BaseModel

class GenState(BaseModel):
    workspace_id: str
    input_text: str
    stories: list[dict] = []
    similar_cases: list[dict] = []
    draft_cases: list[dict] = []

builder = StateGraph(GenState)
builder.add_node("classify_input", classify_input_node)
builder.add_node("chunk_input", chunk_input_node)
builder.add_node("retrieve_rag", retrieve_rag_node)
builder.add_node("search_existing_suite", search_existing_node)
builder.add_node("draft_happy", draft_happy_node)
builder.add_node("draft_edges", draft_edges_node)
builder.add_node("score_priority", score_priority_node)
builder.add_node("stream_emit", stream_emit_node)
builder.add_node("persist_drafts", persist_drafts_node)
builder.set_entry_point("classify_input")
# ... edges
graph = builder.compile(checkpointer=postgres_saver)
```

### 4.2 GENERATION (OpenAPI enrich)

```
load_spec → for_each_operation → deterministic_baseline (call OpenAPI generator)
                                       ↓
                                  ai_propose_edges  ← LLM
                                       ↓
                                  merge_dedup
                                       ↓
                                 stream_emit → persist_drafts → END
```

### 4.3 GENERATION (URL semantic)

```
launch_browser_mcp → snapshot_dom → identify_flows
                                         ↓
                                  for_each_flow:
                                     explore_run (browser-use agentic)
                                         ↓
                                  observe_outcome
                                         ↓
                                  draft_case_from_trace
                                         ↓
                              stream_emit → persist_drafts → END
```

### 4.4 EXECUTION

```
load_case → for_each_step:
   ↓
   classify_step
   ├── code present → execute_code (deterministic via MCP, no LLM)
   ├── action only + tier≠ZERO → agentic_translate (LLM) → execute_translated
   └── action only + tier=ZERO → emit_error(NO_LLM_FOR_AGENTIC_STEP)
   ↓
   capture_artifacts
   ↓
   assert_step
   ├── pass → next step
   └── fail → handoff_to_diagnose (subgraph)
   ↓
END
```

### 4.5 DIAGNOSIS

```
gather_context (logs + recent commits + test code + history)
   ↓
classify_category (REGRESSION / FLAKE / INFRA / SPEC_DRIFT / MANUAL_TRIAGE)
   ↓
draft_diagnosis (structured output via Pydantic)
   ↓
attach_evidence
   ↓
persist_to_defect → optional tracker.create_issue → END
```

### 4.6 CONVERSATION

Lightweight, single-node loop with tool calls. No checkpointer (ephemeral).

```
chat_turn ─ (tool_call?) → invoke_tool → chat_turn → END
```

---

## 5. Capability + autonomy guard

Every task entry MUST pass through `capabilities.py` gates. Pattern:

```python
# suitest_agent/capabilities.py
from enum import Enum, Flag, auto
from fastapi import HTTPException

class Tier(Flag):
    ZERO  = auto()
    LOCAL = auto()
    CLOUD = auto()

class AutonomyLevel(int, Enum):
    MANUAL    = 0
    ASSIST    = 1
    SEMI_AUTO = 2
    AUTO      = 3

class LLMDisabled(HTTPException):
    def __init__(self, hint: str):
        super().__init__(503, detail={"code": "LLM_DISABLED", "hint": hint})

class AutonomyInsufficient(HTTPException):
    def __init__(self, required: AutonomyLevel, current: AutonomyLevel):
        super().__init__(403, detail={
            "code": "AUTONOMY_INSUFFICIENT",
            "required": required.name,
            "current": current.name,
        })

def require_tier(allowed: Tier, *, hint: str = ""):
    def deco(fn):
        async def wrap(*args, ctx, **kw):
            if not (ctx.tier & allowed):
                raise LLMDisabled(hint or "Configure LLM provider to enable.")
            return await fn(*args, ctx=ctx, **kw)
        return wrap
    return deco

def require_autonomy(min_level: AutonomyLevel):
    def deco(fn):
        async def wrap(*args, ctx, **kw):
            if ctx.autonomy < min_level:
                raise AutonomyInsufficient(min_level, ctx.autonomy)
            return await fn(*args, ctx=ctx, **kw)
        return wrap
    return deco
```

Usage:

```python
from suitest_agent.capabilities import require_tier, require_autonomy, Tier, AutonomyLevel

@require_tier(Tier.CLOUD | Tier.LOCAL, hint="Generation needs LLM. Try /generators/openapi.")
@require_autonomy(AutonomyLevel.ASSIST)
async def generate_from_prd(ctx, payload): ...
```

`ctx` (request context) is built by FastAPI dependency from `WorkspaceCapability` + `AutonomyConfig` (see [DATA_MODEL.md](./DATA_MODEL.md) and [AUTONOMY.md](./AUTONOMY.md)).

---

## 6. Base system prompt (v1/system-base.md)

Provider-agnostic. No mention of "Claude" or any specific vendor.

```
You are Suitest Agent, an AI assistant embedded in a test case management
and execution platform. You operate inside a specific mode (GENERATION,
EXECUTION, DIAGNOSIS, or CONVERSATION) supplied at invocation. Read the
mode-specific instructions appended below.

You have access to typed tools. Use them deliberately. Prefer reading
source-of-truth data (DB, code, docs) over guessing.

You are running inside a deployment with the following runtime context:
- capability_tier:  ZERO | LOCAL | CLOUD
- autonomy_level:   manual | assist | semi_auto | auto
- workspace_id:     {workspace_id}
- session_kind:     {GENERATION|EXECUTION|DIAGNOSIS|CONVERSATION}

Adjust behavior to autonomy_level:
- assist:     propose artifacts, never finalize. Always end with a clear
              "Awaiting human review" handoff and DRAFT status.
- semi_auto:  finalize P2/P3 artifacts; mark P0/P1 as DRAFT.
- auto:       finalize all artifacts without asking the user, but respect
              safety rails (never delete data, never close defects, never
              push to main directly). Audit every autonomous action.

Style guide:
- Be concise. Engineers don't want fluff.
- When recommending changes, cite specific files, line numbers, or commit SHAs.
- When uncertain, say so and propose a verification step instead of guessing.
- Use Bahasa Indonesia for greetings if the user does. Use English for code,
  identifiers, and technical content.

Hard rules (enforced even in auto):
- Never fabricate test case IDs, commit hashes, or file paths.
- Never claim a test passed unless an EXECUTION run reports PASS.
- Never close a defect — only humans close defects.
- Never delete test cases or suites autonomously.
- Never push to main directly — always via PR.
- Never store credentials or PII in test case content or logs.
```

Prompts versioned by directory (`v1/`, `v2/`) and pinned by SHA-256 of file content at session start (`AgentSession.prompt_version_id = "v1/generate-from-prd@sha256:abcd..."`).

**Content drift detection.** On every prompt load (`prompts/loader.py`), the loader computes SHA-256 of the prompt file content and compares against the `prompt_versions.hash` stored in DB (see [DATA_MODEL.md §4.5](./DATA_MODEL.md#45-prompt_versions--versioned-prompts)). Mismatch raises `PromptDriftError`, which the API converts to **`500 PROMPT_DRIFT`** with a hint to bump the prompt version explicitly:

```python
# packages/agent/suitest_agent/prompts/loader.py
class PromptDriftError(RuntimeError):
    """Raised when on-disk prompt SHA-256 does not match the stored prompt_versions.hash."""

def load(name: str, version: str) -> str:
    on_disk = (PROMPTS_ROOT / version / f"{name}.md").read_text()
    computed = hashlib.sha256(on_disk.encode()).hexdigest()
    stored = await prompt_versions_repo.get_hash(name=name, version=version)
    if stored and stored != computed:
        raise PromptDriftError(
            f"Prompt {version}/{name} drifted: disk={computed[:8]}, db={stored[:8]}. "
            f"Bump the version (create v{int(version[1:]) + 1}) instead of editing in place."
        )
    return on_disk
```

**No silent rewrite.** The loader never auto-updates the stored hash. Operators must create a new `prompt_versions` row (`v1` → `v2`) when intentionally changing prompt content; this preserves replay integrity for historical sessions.

---

## 7. Tool definitions

All tools defined in `tools/registry.py` using Pydantic schemas, then converted to LiteLLM/OpenAI tool-use JSON via `model_json_schema()`. Each tool declares minimum tier + minimum autonomy.

```python
from pydantic import BaseModel, Field
from suitest_agent.capabilities import Tier, AutonomyLevel

class ToolSpec(BaseModel):
    name: str
    description: str
    schema: type[BaseModel]
    min_tier: Tier = Tier.ZERO
    min_autonomy: AutonomyLevel = AutonomyLevel.ASSIST
    mutates: bool = False         # if true, agent in conversation mode must confirm

# Example: docs.read
class DocsReadArgs(BaseModel):
    query: str = Field(..., description="Natural-language query or section id.")
    document_id: str | None = Field(None, description="Optional: scope to one doc.")
    max_chunks: int = Field(8, ge=1, le=32)

DOCS_READ = ToolSpec(
    name="docs.read",
    description="Read sections from indexed documents (PRD, OpenAPI, URL crawls).",
    schema=DocsReadArgs,
)
```

### Tool catalog (v1)

| Tool | Purpose | min_tier | mutates |
|------|---------|:--------:|:-------:|
| `docs.read` | Semantic + FTS chunk retrieval | ZERO | no |
| `docs.list_endpoints` | OpenAPI endpoint list | ZERO | no |
| `code.read` | Read file at HEAD (GitHub App or local) | ZERO | no |
| `mcp.invoke` | Generic dispatch to any MCP tool | ZERO | depends |
| `mcp.discover_tools` | List tools an MCP server exposes | ZERO | no |
| `mcp.invoke_typed` | Typed dispatch (Pydantic-validated args) | ZERO | depends |
| `db.query_cases` | Filter test cases | ZERO | no |
| `db.query_runs` | Filter runs | ZERO | no |
| `db.query_defects` | Filter defects | ZERO | no |
| `search.suite` | Vector + keyword search over existing cases | ZERO | no |
| `target.classify` | Deterministic target classifier (BE_REST etc.) | ZERO | no |
| `cases.create` | Create DRAFT test case | CLOUD\|LOCAL | yes |
| `case.export` | Export case to Playwright/Cypress/Selenium code | ZERO | no |
| `defect.create` | File defect from run failure | ZERO | yes |
| `tracker.create_issue` | Sync to Jira/Linear/GitHub | ZERO | yes |

`mcp.invoke` (generic):

```python
class McpInvokeArgs(BaseModel):
    provider_id: str = Field(..., description="MCP server id from /mcp/providers.")
    tool: str
    args: dict
```

`mcp.discover_tools` (new):

```python
class McpDiscoverArgs(BaseModel):
    provider_id: str

class McpToolInfo(BaseModel):
    name: str
    description: str
    input_schema: dict        # JSON Schema as returned by MCP server
```

`mcp.invoke_typed` validates `args` against the discovered schema before dispatching, surfacing a structured error to the LLM if invalid (helps LLM self-correct).

`target.classify` is the same deterministic classifier used by generators ([GENERATORS.md § 2](./GENERATORS.md)); exposed as a tool so the agent can route follow-up generation without re-implementing the rule table.

`case.export(case_id, target)` produces a code file in the chosen framework. Output stored as an artifact; agent returns the artifact URL.

Tool subset per mode (registered in `tasks/<mode>.py`):

| Mode | Tools registered |
|------|------------------|
| GENERATION | `docs.read`, `docs.list_endpoints`, `search.suite`, `target.classify`, `cases.create`, `case.export`, `mcp.discover_tools` |
| EXECUTION | `mcp.invoke`, `mcp.invoke_typed`, `mcp.discover_tools`, `db.query_cases` |
| DIAGNOSIS | `code.read`, `db.query_runs`, `db.query_defects`, `defect.create`, `tracker.create_issue` |
| CONVERSATION | `docs.read`, `db.query_*`, `search.suite` (read-only; mutating tools blocked unless explicit UI confirm) |

---

## 8. Generation pipeline (LLM-driven)

LLM-driven generation supports 3 sources only — **OpenAPI is owned by the deterministic generator** ([GENERATORS.md § 4.1](./GENERATORS.md)), with optional AI-enrich as a hybrid.

### 8.1 PRD natural language

LangGraph: `graphs/generate_from_prd.py`. See § 4.1 above for node diagram.

Prompt v1/generate-from-prd.md (excerpt):

```
For each user story or acceptance criterion in the supplied PRD chunks:
1. Identify actor, action, and expected outcome.
2. Draft ONE happy-path case covering the success scenario.
3. Add 1-3 variant cases for edge conditions (denial, error states,
   boundary values, race conditions).
4. Each step must include:
   - action:   imperative, single user action
   - expected: observable outcome with specific selectors/values
   - target_kind: classifier result (call target.classify if unsure)
   - mcp_provider: from /mcp/providers given target_kind

Avoid:
- Generic "verify the page works" assertions
- Multi-action steps ("click the button and fill the form")
- Coverage of areas not in the supplied requirement

Emit one case per `cases.create` tool call. End by listing the case IDs
you created.
```

### 8.2 URL semantic (browser-use AI)

LangGraph: `graphs/generate_from_url_semantic.py`. Uses **browser-use** Python library driving the configured browser MCP. Agent has full semantic awareness ("checkout flow", "registration"). See § 4.3.

### 8.3 MCP tool discovery

Agent connects to a custom MCP server via `mcp.discover_tools`, explores each tool semantically (toolname + description + sample inputs), generates test cases that exercise each tool with valid + invalid inputs. `target_kind = CUSTOM`.

### 8.4 OpenAPI enrich (hybrid)

LangGraph: `graphs/generate_from_openapi_ai.py`. Workflow:

1. Call deterministic OpenAPI generator ([GENERATORS.md § 4.1](./GENERATORS.md)) → emits N baseline cases.
2. For each operation, AI proposes additional edge cases based on natural-language description + examples (cases the deterministic rules can't infer).
3. Merge + dedupe (Levenshtein on case name + step signature).
4. User reviews merged set in UI before approval.

---

## 9. Execution pipeline

Per-step decision tree (LangGraph node `classify_step`):

```
                  step has step.code?
                  │
        ┌─────────┴─────────┐
       YES                  NO
        │                    │
        ↓                    ↓
  execute_code         step has step.action?
  (deterministic       │
   via mcp.invoke,     ↓
   no LLM)        ┌────┴────┐
                 YES        NO
                  │          │
                  ↓          ↓
         tier == ZERO?    emit_error(MALFORMED_STEP)
              │
       ┌──────┴──────┐
      YES            NO
       │              │
       ↓              ↓
  emit_error      agentic_translate (LLM)
  (NO_LLM_FOR_         │
   AGENTIC_STEP)       ↓
                  autonomy gate
                  │
        ┌─────────┴─────────┐
      ASSIST            SEMI_AUTO / AUTO
        │                    │
        ↓                    ↓
  prompt_user_confirm   execute_translated
  via WS, await           │
  approval                ↓
        │           capture_artifacts
        ↓                    │
  execute_translated         │
        │                    │
        └─────────┬──────────┘
                  ↓
              assert_step
```

Autonomy effect on EXECUTION:

| Level | Behavior |
|-------|----------|
| `manual` | Run never engages agent. Only `step.code` paths execute; agentic steps marked `SKIPPED_NO_AUTONOMY`. |
| `assist` | Each agentic step pauses run, emits `agent.step.confirm_required` WS event, awaits user click. 5-minute timeout → mark SKIPPED. |
| `semi_auto` | Agentic steps run through without prompt. On failure, diagnosis runs in shadow but defect stays DRAFT for P0/P1. |
| `auto` | Full agentic + (in v1.x) self-heal: agent re-generates selectors when DOM drift detected, retries once. |

---

## 10. Diagnosis pipeline

Triggered automatically when a step fails OR explicitly via `POST /agent/diagnose/runs/:id`. Requires `tier != ZERO`.

```
gather_context:
  - failed step action + expected + actual assertion message
  - console logs from MCP session
  - last N commits touching files in stack trace (via code.read)
  - prior runs of same test case (was it always failing?)
  - test code if available

classify_category → REGRESSION | FLAKE | INFRA | SPEC_DRIFT | MANUAL_TRIAGE

draft_diagnosis → Pydantic-validated structured output:
```

```python
class Diagnosis(BaseModel):
    root_cause: str = Field(..., max_length=400)          # 1-2 sentences
    confidence: float = Field(..., ge=0.0, le=1.0)
    category: Literal["REGRESSION", "FLAKE", "INFRA", "SPEC_DRIFT", "MANUAL_TRIAGE"]
    evidence_files: list[EvidenceRef]
    suggested_fix: str | None = None
    rerun_recommended: bool = False
```

### ZERO tier fallback (rule-based)

```python
# suitest_agent/tasks/diagnosis.py
ZERO_RULES = [
    (r"timeout|timed out", "INFRA"),
    (r"ECONNREFUSED|ECONNRESET", "INFRA"),
    (r"expected .* to (equal|be|contain)", "MANUAL_TRIAGE"),
    (r"element .* not found", "MANUAL_TRIAGE"),
]

def diagnose_zero(assertion_message: str) -> Diagnosis:
    for pat, cat in ZERO_RULES:
        if re.search(pat, assertion_message, re.I):
            return Diagnosis(
                root_cause="Heuristic categorization (ZERO tier, no LLM).",
                confidence=0.3,
                category=cat,
                evidence_files=[],
                suggested_fix=None,
            )
    return Diagnosis(
        root_cause="No matching rule.",
        confidence=0.1,
        category="MANUAL_TRIAGE",
        evidence_files=[],
    )
```

ZERO diagnoses always carry `confidence ≤ 0.3` and `category = MANUAL_TRIAGE` unless an infra pattern matches. UI surfaces the lower confidence prominently.

---

## 11. Conversation pipeline

`tasks/conversation.py`. Always picks the smallest available model from the configured provider via `LLMConfig.preferred_models["conversation"]`.

- Read-only tools: `docs.read`, `db.query_*`, `search.suite`.
- Mutating tools (`cases.create`, `defect.create`, `tracker.create_issue`) blocked at the registry layer for CONVERSATION mode unless the UI sends `confirm: true` from an explicit user click.
- Context window: last 20 turns + workspace context (current route, currently selected entity ID) + tier/autonomy.
- No LangGraph checkpointer (chats are ephemeral; resumability via standard chat history).

---

## 12. Streaming protocol

LiteLLM streaming chunks are normalized in `sessions/streaming.py` and re-emitted as Suitest domain events over FastAPI SSE (`/agent/sessions/:id/stream`) or WebSocket room (`agent-session:<id>`).

```python
# sessions/streaming.py (sketch)
async def to_suitest_events(session_id: str, chunks):
    async for chunk in chunks:
        delta = chunk.choices[0].delta
        if delta.content:
            yield {"type": "agent.message.delta",
                   "session_id": session_id,
                   "role": "AGENT",
                   "content_delta": delta.content}
        for tc in (delta.tool_calls or []):
            if tc.function.name and not tc.id_seen:
                yield {"type": "agent.tool.start",
                       "session_id": session_id,
                       "tool_call_id": tc.id,
                       "tool_name": tc.function.name,
                       "input_delta": tc.function.arguments or ""}
            else:
                yield {"type": "agent.tool.input.delta",
                       "session_id": session_id,
                       "tool_call_id": tc.id,
                       "input_delta": tc.function.arguments or ""}
```

Event types (frontend subscribes via `@ai-sdk/react` + `assistant-ui` adapter):

| Event | Payload |
|-------|---------|
| `agent.session.started` | `{session_id, mode, model, prompt_version_id}` |
| `agent.message.delta` | `{session_id, role, content_delta}` |
| `agent.tool.start` | `{session_id, tool_call_id, tool_name, input_delta}` |
| `agent.tool.input.delta` | `{session_id, tool_call_id, input_delta}` |
| `agent.tool.end` | `{session_id, tool_call_id, tool_name, output, duration_ms}` |
| `agent.case.created` | `{session_id, case_id, status: "DRAFT"}` (GENERATION) |
| `agent.step.confirm_required` | `{session_id, step_id, proposed_action}` (assist EXECUTION) |
| `agent.diagnosis.ready` | `{session_id, defect_id, confidence}` |
| `agent.session.completed` | `{session_id, outcome, cost_usd, tokens_in, tokens_out}` |
| `agent.session.error` | `{session_id, code, message}` |

---

## 13. Reproducibility

Every `AgentSession` row persists enough to deterministically (or near-deterministically) replay:

| Field | Description |
|-------|-------------|
| `prompt_version_id` | `v1/generate-from-prd@sha256:abcd...` |
| `model_id` | Full LiteLLM model id (`anthropic/claude-sonnet-4-5`) |
| `provider` | Workspace LLMConfig provider at time of run |
| `seed` | If provider supports seeded sampling (OpenAI, vLLM, llama.cpp) |
| `temperature`, `max_tokens` | Sampling params |
| `messages` | Full conversation log, including tool calls + tool results, stored in `AgentSession.messages` (JSONB) |
| `tool_call_trace` | Ordered list of `{tool, args, result, duration_ms, error?}` |
| `rag_chunks` | IDs + content hashes of all chunks retrieved |
| `cost_usd` | LiteLLM `completion_cost()` per call, summed |

`GET /agent/sessions/:id/replay` returns the full trace. `POST /agent/sessions/:id/replay?dry_run=true` re-executes against the same provider+model+seed and diffs the output (read-only; never mutates DB). Useful for prompt regression testing and debugging non-determinism.

### 13.1 Seed handling (provider divergence)

- **Anthropic API does NOT support a `seed` parameter** (unlike OpenAI / Groq / vLLM / llama.cpp). LiteLLM silently drops `seed` for Anthropic via `litellm.drop_params = True` (see [§3](#3-litellm-integration)).
- For Anthropic-backed sessions, `agent_sessions.seed` is stored as `null` — there is no seed to persist because the provider would not honour it.
- The replay endpoint response includes a `determinism` field reflecting provider capability:

```json
// GET /agent/sessions/:id/replay (Anthropic session)
{
  "session_id": "sess_xxx",
  "determinism": "best_effort",
  "reason": "Anthropic API does not support seed; replay may diverge.",
  "prompt_version_id": "v1/generate-from-prd@sha256:abcd...",
  "messages": [ ... ]
}

// GET /agent/sessions/:id/replay (OpenAI session, seed set)
{
  "session_id": "sess_yyy",
  "determinism": "deterministic",
  "seed": 42,
  "prompt_version_id": "v1/generate-from-prd@sha256:abcd...",
  "messages": [ ... ]
}
```

| Provider | Seed support | `determinism` value |
|----------|:------------:|---------------------|
| `anthropic` | ✗ | `best_effort` |
| `openai` | ✓ | `deterministic` |
| `groq` | ✓ | `deterministic` |
| `vllm`, `llamacpp` | ✓ | `deterministic` |
| `ollama` | partial (model-dependent) | `best_effort` |
| `gemini` | ✗ | `best_effort` |
| `bedrock`, `vertex` | depends on underlying model | `best_effort` |
| `mock` | ✓ (hash-based) | `deterministic` |

---

## 14. Cost & quota

LiteLLM `completion_cost(completion_response=resp)` returns USD per call. Aggregated:

- Per-session: `AgentSession.cost_usd` (final, on completion)
- Per-workspace: rolling 24h sum + 30d sum via background task
- Per-user: same, scoped by `AgentSession.user_id`

### Budget guard

```python
# capabilities.py
class WorkspaceBudget(BaseModel):
    daily_usd: float = 5.00
    monthly_usd: float = 100.00
    soft_cap_pct: float = 0.80      # downgrade trigger
    hard_cap_pct: float = 1.00      # block

async def enforce_budget(workspace_id: str, model_call: ModelCall):
    today = await sum_cost_today(workspace_id)
    budget = await load_budget(workspace_id)
    if today >= budget.daily_usd * budget.hard_cap_pct:
        raise BudgetExceeded()
    if today >= budget.daily_usd * budget.soft_cap_pct:
        model_call.model = downgrade_map.get(model_call.model, model_call.model)
    return model_call
```

Default downgrade map (configurable per workspace):

| From | To |
|------|----|
| `anthropic/claude-sonnet-*` | `anthropic/claude-haiku-*` |
| `openai/gpt-4o` | `openai/gpt-4o-mini` |
| `gemini/gemini-1.5-pro` | `gemini/gemini-1.5-flash` |
| `ollama/llama3.1:70b` | `ollama/llama3.1:8b` |

Hard cap returns `HTTP 429 BUDGET_EXCEEDED` with hint to raise budget.

---

## 15. Testing the agent

```bash
# unit
uv run pytest packages/agent/tests/

# eval (LLM call, requires SUITEST_LLM_API_KEY)
uv run python -m suitest_agent.eval run --fixture packages/agent/suitest_agent/eval/fixtures/prds/
```

### Mock provider

`providers/mock.py` returns canned, deterministic responses based on input hashes. Used in:

- `pytest` unit tests
- CI integration tests (no real LLM cost)
- Local dev when `SUITEST_LLM_PROVIDER=mock`

Snapshot-style assertions:

```python
@pytest.mark.asyncio
async def test_generate_from_prd_yields_3_to_8_cases(mock_provider, prd_fixture):
    result = await generate.from_prd(prd_fixture, ctx=fake_ctx_cloud)
    assert 3 <= len(result.cases) <= 8
    for case in result.cases:
        assert case.status == "DRAFT"
        assert all("action" in s and "expected" in s for s in case.steps)
        assert case.steps[0]["target_kind"] in {"BE_REST","FE_WEB","DATA","INFRA","MIXED","CUSTOM"}
```

### Eval suite

`suitest_agent/eval/fixtures/`:

- `prds/` — 20 PRDs with expected case-count ranges + target_kind distribution
- `openapi/` — 10 specs with expected contract test count per operation
- `failed_runs/` — 15 fixtures with known root-cause category

Eval CLI emits a JSON report + Prometheus push. Targets: PRD ≥ 80% structural conformance, OpenAPI-enrich ≥ 95% baseline preserved, Diagnosis ≥ 70% correct category. Schema-only in v1.0; full eval-UI in v1.x ([ROADMAP.md](./ROADMAP.md)).

---

## 16. Observability

### OpenTelemetry

```python
# observability/tracing.py
from opentelemetry import trace
tracer = trace.get_tracer("suitest.agent")

async def run_task(...):
    with tracer.start_as_current_span("agent.session") as span:
        span.set_attributes({
            "agent.mode": mode,
            "agent.model": model,
            "agent.workspace_id": workspace_id,
            "agent.tier": tier.name,
            "agent.autonomy": autonomy.name,
            "agent.prompt_version_id": pv_id,
        })
        ...
        with tracer.start_as_current_span("agent.llm_call") as call_span:
            call_span.set_attributes({
                "llm.tokens_in": usage.prompt_tokens,
                "llm.tokens_out": usage.completion_tokens,
                "llm.cost_usd": cost,
            })
```

Exported to OTLP endpoint (configurable). Default compose ships Jaeger.

### Prometheus metrics

- `suitest_agent_session_duration_seconds{mode}`
- `suitest_agent_tokens_total{mode, direction}`
- `suitest_agent_cost_usd_total{workspace_id, provider}`
- `suitest_agent_tool_calls_total{tool}`
- `suitest_agent_generation_yield{source}` (cases/req histogram)
- `suitest_agent_llm_errors_total{provider, code}`

### Langfuse (optional)

If `LANGFUSE_HOST` + `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` are set, every LiteLLM call is forwarded via LiteLLM's built-in Langfuse callback. The docker-compose stack ships an optional `langfuse` service (compose profile `observability`) for self-hosted prompt/response audit + cost dashboards.

```yaml
# docker-compose excerpt
services:
  langfuse:
    profiles: ["observability"]
    image: langfuse/langfuse:latest
    environment:
      DATABASE_URL: postgresql://langfuse:...@db:5432/langfuse
      NEXTAUTH_SECRET: ${LANGFUSE_NEXTAUTH_SECRET}
      SALT: ${LANGFUSE_SALT}
    ports: ["3030:3000"]
```

---

## 17. Future

Roadmap pointers (full list: [ROADMAP.md](./ROADMAP.md)):

- **v1.x** — eval harness UI, custom agent definitions, diff-aware test selection, cost dashboard, plugin SDK, prompt fork per workspace
- **v2.x** — self-healing tests (auto re-select on DOM drift), visual regression with AI explanation, mobile (appium-mcp), desktop (computer-use MCP), multi-agent swarm (Planner / Executor / Critic), PR codegen patches
