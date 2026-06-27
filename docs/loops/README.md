# Engineering loop backlog — gap-driven, QA-user lens

> These documents are the **backlog** that feeds the loop engine in
> [`SESSION_LOOP.md`](../../SESSION_LOOP.md). `SESSION_LOOP.md` is *how* we work
> (TDD baseline → RED → GREEN → verify → commit). These docs are *what* to work
> on next, and *why*.

## Whose perspective

Written from the seat of a **QA engineer who will USE Suitest**, not from the
seat of the person building it. The ordering principle that falls out of that
lens (see the conversation that produced these docs):

1. **ZERO tier is the backbone, not the budget option.** Most OSS adopters start
   with no LLM key: self-host, wire MCP servers, run deterministic tests in CI.
   Execution must *never* need an LLM. Get ZERO flawless first.
2. **LLM is topping on AUTHORING + TRIAGE, not execution.** Even a CLOUD-tier
   shop runs its regression suite deterministically. The LLM earns its keep
   cold-starting suites (generation) and categorizing failures (diagnosis).
3. **Embeddings is a third, independent dial** (fastembed = local, ZERO-safe).

So the loop order is: **finish [`ZERO_TIER_GAPS.md`](./ZERO_TIER_GAPS.md) first,
then [`LLM_TIER_GAPS.md`](./LLM_TIER_GAPS.md).**

## The tier-seam rule (important)

Some roadmap milestones bundle a deterministic part and an LLM part. **Split them
along the tier seam, not along the feature line.** The deterministic half belongs
in the ZERO doc; the LLM half in the LLM doc. Examples already split below:

| Milestone | ZERO half (deterministic) | LLM half |
|-----------|---------------------------|----------|
| M11 visual regression | screenshot pixel/perceptual diff → `Z8` | vision-LLM "why it changed" → `L4` |
| M12 mobile | `appium-mcp` step execution → `Z9` | mobile case generation |
| M13 desktop | `computer-use-mcp` step execution → `Z9` | desktop case generation |

This is the whole point of the capability-tier design: the deterministic core
ships and runs without the LLM; the LLM is enrichment on top.

## Per-item template

Every backlog item is shaped for the loop so the work is unambiguous:

```
### <ID> — <title>
- **Goal (done =):**  one testable sentence. What proves it shipped.
- **Why (QA-user):**  the value from the user's chair.
- **State:**          BUILT / PARTIAL / MISSING — evidence at file:line.
- **Tier / gates:**   ZERO or CLOUD|LOCAL; require_tier / require_autonomy / audit.
- **Loop prompt:**    the prompt to paste into the SESSION_LOOP.md TDD loop.
- **Done-check:**     the command / assertion that must go green.
```

## How to run one loop iteration

1. Read [`SESSION_LOOP.md`](../../SESSION_LOOP.md) §1–§2. Capture a valid baseline
   (`make test` → `/tmp/suitest_baseline.txt`). Never skip the baseline.
2. Pick the **lowest unstarted ID** in `ZERO_TIER_GAPS.md` (ZERO before LLM).
3. Paste its **Loop prompt** into the TDD loop. RED → GREEN → REFACTOR.
4. Run the item's **Done-check** plus `make check-all` + `make test`. All green.
5. Conventional commit, no `Co-Authored-By` trailer (repo preference).
6. Tick the item here, move to the next ID.

## Status legend

- **MISSING** — no code exists.
- **PARTIAL** — schema/field/scaffold exists; behavior not wired end-to-end.
- **BUILT** — works; listed only when an item depends on it.
