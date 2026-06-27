# LLM-tier gap backlog (do this after the ZERO backbone holds)

> Loop backlog for **LLM-dependent enrichment** — CLOUD/LOCAL tier only. Every
> item here is **AUTHORING** or **TRIAGE** help; none of it touches deterministic
> execution. Read [`README.md`](./README.md) for the template + ordering and
> [`SESSION_LOOP.md`](../../SESSION_LOOP.md) for the TDD mechanics.
>
> **Non-negotiable per CLAUDE.md §4:** every new endpoint declares
> `Depends(require_tier(Tier.CLOUD | Tier.LOCAL))`; side-effecting agent steps add
> `require_autonomy(...)`; UI wraps in `<Gated>`; the default code path still works
> in ZERO. LLM calls go through `packages/agent` (LiteLLM), never the SDK from a
> route. Mock the LLM first (`providers/mock.py`), real provider last.

## What's already BUILT (do not redo — build ON these)

| Capability | Evidence |
|-----------|----------|
| PRD → cases generator | `packages/agent/src/suitest_agent/generators/prd.py` |
| URL-semantic generator | `packages/agent/src/suitest_agent/generators/url_semantic.py` |
| MCP-discovery generator | `packages/agent/src/suitest_agent/generators/mcp_discovery.py` |
| **AI diagnosis** (REGRESSION/FLAKE/INFRA/SPEC_DRIFT/MANUAL_TRIAGE + confidence + root cause + suggested fix) | `packages/agent/src/suitest_agent/graphs/diagnosis.py`; wired via `services/defect_auto_filer.py` (`enable_llm_diagnosis` gate) |
| Diff-aware test selection (M6) | `packages/agent/src/suitest_agent/generators/diff_selector.py` |
| Cost budget guard / auto-downgrade (M7) | `packages/agent/src/suitest_agent/providers/litellm_router.py` |
| Custom agent + plugin SDK (M8/M9) | `packages/agent/src/suitest_agent/plugin_sdk/base.py` |
| Provider layer (LiteLLM 100+, mock, tier gating) | `packages/agent/src/suitest_agent/providers/base.py` |
| Prompt versioning + drift guard + per-workspace fork | `packages/agent/src/suitest_agent/prompts/loader.py` |

> **Correction worth noting:** AI diagnosis — the highest recurring TRIAGE value —
> is already BUILT. The remaining diagnosis gap is *evidence quality*: it can't yet
> cite ingested requirements/specs because RAG retrieval is missing (`L1`). So the
> RAG pipeline is the unlock for both better authoring **and** better triage.

---

## Backlog (loop order = top to bottom)

### L1 — RAG pipeline: ingest + chunker + retriever
- **Goal (done =):** A document (PRD / OpenAPI / URL crawl) can be ingested →
  chunked → embedded → stored in `document_chunks`, and retrieved top-k by
  pgvector cosine with a Postgres FTS fallback at ZERO/embeddings-off. HNSW index
  created.
- **Why (QA-user):** This is the keystone. It unblocks doc-grounded generation
  (less hallucination), `docs.read`/`search.suite` agent tools (`L2`), and
  evidence-cited diagnosis. Schema is already in place; only the runtime is gone.
- **State:** PARTIAL — `packages/db/src/suitest_db/models/document.py` has
  `Document` + `DocumentChunk` (pgvector `Vector(None)`); **no** `chunker.py`,
  **no** `retriever.py`, HNSW index still `TODO(M1b+)` in the documents migration.
- **Tier / gates:** Embedding is ZERO-safe (fastembed); the *generation* that
  consumes RAG is CLOUD|LOCAL. Per-workspace vector dim per DATA_MODEL §13.
- **Loop prompt:**
  > Build the RAG runtime against the existing Document/DocumentChunk schema.
  > 1) `chunker.py` — markdown- and code-fence-aware chunking. 2) ingest service
  > — chunk → embed (reuse `suitest_core.embeddings.get_embedder`) → persist
  > chunks + `indexed_at`. 3) `retriever.py` — top-k pgvector cosine
  > (`embedding.cosine_distance`) scoped to workspace, with Postgres FTS fallback
  > when embeddings are off (ZERO). 4) Alembic migration for the HNSW index
  > (`vector_cosine_ops`) per DATA_MODEL §7.2. TDD: failing retriever test (mock
  > embedder) that an ingested doc returns its relevant chunk by query, and that
  > embeddings-off falls back to FTS; then implement.
- **Done-check:** test: ingest a doc → query returns the right chunk via vector;
  same query with `SUITEST_EMBEDDINGS=none` returns it via FTS.

### L2 — Agent tools: `docs.read` + `search.suite`
- **Goal (done =):** LangGraph generation agents can call `docs.read` (retrieve
  doc chunks via `L1`) and `search.suite` (vector+keyword over existing cases) so
  generation cites requirements and avoids duplicating existing cases.
- **Why (QA-user):** Cuts hallucinated and duplicate generated cases — the two
  things that make QA distrust AI authoring. Directly improves DRAFT quality, so
  review burden drops.
- **State:** PARTIAL — capabilities named in `schemas/capabilities.py`
  (`semantic_search`, `fts_search`); no LangGraph tool implementations in
  `graphs/`.
- **Tier / gates:** CLOUD|LOCAL. Record retrieved chunk IDs/hashes on the
  `AgentSession` (AI_AGENT.md `rag_chunks`) for auditability.
- **Loop prompt:**
  > Implement `docs.read` and `search.suite` as agent tools over the `L1`
  > retriever and the existing case search. Generation graphs (PRD, url-semantic,
  > mcp-discovery) call `search.suite` before emitting drafts and dedupe against
  > hits (Levenshtein on name + step signature, per AI_AGENT.md §8.x). Persist
  > retrieved chunk IDs on the AgentSession. TDD: failing test that a generated
  > draft duplicating an existing case is suppressed/merged; then wire the tools.
- **Done-check:** test: generation against a suite already containing case X does
  not emit a near-duplicate of X; AgentSession records the retrieved chunk IDs.

### L3 — Self-healing tests (M10)
- **Goal (done =):** When a step fails on a selector-not-found, the agent
  proposes an updated selector from the current DOM/snapshot; the fix is saved
  **only** under `auto` autonomy, audited and reversible.
- **Why (QA-user):** Selector churn is the #1 maintenance tax in UI testing.
  Auto-repair (gated) turns a red suite from "an afternoon of edits" into "review
  a diff." After diagnosis, the highest QA-value LLM feature.
- **State:** MISSING — ROADMAP M10-1..M10-4 all `[ ]`, no code.
- **Tier / gates:** CLOUD|LOCAL **and** `require_autonomy(AutonomyLevel.AUTO)` to
  persist a change (M10-3/M10-4). Below `auto` → propose only, never save. Audit
  every applied repair.
- **Loop prompt:**
  > Implement self-healing (ROADMAP M10). M10-1: detect selector-change failures
  > from the runner's error signal. M10-2: agent proposes an updated step from the
  > current page snapshot via `packages/agent` (mock provider first). M10-3: save
  > the updated step ONLY under `auto` autonomy, audit-logged and reversible;
  > otherwise surface as a suggestion. TDD: failing test that (a) a selector
  > failure yields a proposal and (b) it is NOT persisted below `auto` autonomy
  > but IS at `auto`; then implement. Default path must no-op in ZERO.
- **Done-check:** test: selector failure → proposal returned; persisted only at
  `auto`; audit row on apply; ZERO tier returns no proposal.

### L4 — Visual change explanation (LLM half of M11)
- **Goal (done =):** Given the deterministic screenshot diff from `Z8`, a vision
  LLM produces a human reason ("button color changed green→blue", "layout shifted
  on mobile") attached to the case result.
- **Why (QA-user):** A red pixel-diff says *that* something changed; QA needs
  *what* changed to triage fast. Pure enrichment on top of the ZERO diff.
- **State:** MISSING — ROADMAP M11-2 `[ ]`. Depends on `Z8` shipping the diff.
- **Tier / gates:** CLOUD|LOCAL (vision-capable model). Degrades to "diff only,
  no explanation" when no LLM.
- **Loop prompt:**
  > Implement M11-2 on top of the Z8 diff. Feed baseline + current screenshot (and
  > the diff) to a vision model via `packages/agent`; attach a short structured
  > explanation to the case result. Must degrade cleanly to "diff only" in ZERO.
  > Mock the vision provider first. TDD: failing test that a known color-change
  > diff yields an explanation field and that ZERO tier yields the diff with no
  > explanation; then implement.
- **Done-check:** test: changed screenshot → explanation present at CLOUD/LOCAL,
  absent (diff still present) at ZERO.

### L5 — PR codegen patches (M15)
- **Goal (done =):** A defect diagnosed as `REGRESSION` (via the existing
  diagnosis graph) can trigger an agent to draft a fix and open a PR through the
  GitHub integration — strong audit, review gates, **never auto-merge**.
- **Why (QA-user):** Closes the loop from "test caught a regression" to "here's a
  proposed fix to review." High value but high blast radius — ships last, behind
  the strictest gates.
- **State:** MISSING — ROADMAP M15-1..M15-3 all `[ ]`, no code.
- **Tier / gates:** CLOUD|LOCAL **and** `require_autonomy(AutonomyLevel.AUTO)`
  **and** GitHub write scope. No auto-merge default (M15-3). Audit everything.
- **Loop prompt:**
  > Implement M15 on top of the diagnosis graph. When diagnosis = REGRESSION and
  > autonomy = auto and GitHub write scope is present, the agent drafts a patch and
  > opens a PR (never merges). All external calls go through the existing
  > `WebhookRetryQueue`. Strong audit + a human review gate before any PR is
  > opened. TDD: failing test that a REGRESSION diagnosis under `auto` produces a
  > PR-open request (mock GitHub) and that anything less than auto/scope does NOT;
  > then implement.
- **Done-check:** test: REGRESSION + auto + scope → PR-open call (mocked), audit
  row; missing any precondition → no external call.

### L6 — Multi-agent swarm (M14)
- **Goal (done =):** A LangGraph Planner + Executor + Critic orchestration with an
  inter-agent message bus produces higher-quality complex multi-step E2E cases
  than the single-shot generators.
- **Why (QA-user):** Most speculative, least direct daily value — useful for
  generating genuinely complex journeys, but only worth it once authoring quality
  (`L1`/`L2`) and the higher-frequency features land. Ships last.
- **State:** MISSING — ROADMAP M14-1..M14-3 all `[ ]`, no code.
- **Tier / gates:** CLOUD|LOCAL. Reuse cost budget guard (M7) — multi-agent burns
  tokens fast.
- **Loop prompt:**
  > Implement M14 swarm. LangGraph graph with Planner → Executor → Critic nodes
  > and an inter-agent message bus; Critic can send work back to Planner. Target:
  > higher-quality multi-step E2E generation vs single-shot. Enforce the M7 cost
  > budget guard across the whole swarm run. Mock provider first. TDD: failing
  > test that the Critic can reject + re-route a draft and that total spend
  > respects the budget cap; then implement.
- **Done-check:** test: Critic rejection re-routes to Planner; swarm run aborts
  when the cost budget is exceeded.

---

## Suggested ordering rationale

`L1` (RAG keystone — unlocks authoring quality + cited triage) → `L2` (dedup +
grounding via agent tools) → `L3` (self-healing: biggest maintenance win) → `L4`
(visual explanation, needs `Z8`) → `L5` (PR codegen, high blast radius) → `L6`
(swarm, most speculative). Diagnosis is already built; its improvement rides on
`L1`. Cost guard (M7) already protects all of the above.
