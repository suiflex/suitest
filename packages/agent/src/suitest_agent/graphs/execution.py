"""EXECUTION mode graph (M3-4, docs/AI_AGENT.md §4.4).

For each step: a step with executable ``code`` runs deterministically (no LLM); an
``action``-only step is translated to one MCP tool call via the LLM when the tier
permits; an ``action``-only step at ZERO tier yields ``NO_LLM_FOR_AGENTIC_STEP``.

This graph performs *classification + translation* only — the actual MCP dispatch
is the runner's job (M1c / M3-10). It returns a per-step plan in state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from suitest_agent.graphs._util import complete_with_prompt, parse_json_object
from suitest_agent.prompts.loader import load

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from suitest_agent.providers.base import LLMProvider

# A step is {"action": str, "code": str|None, "mcp_provider": str|None}.
Step = dict[str, object]
StepPlan = dict[str, object]


class ExecutionState(TypedDict, total=False):
    case_id: str
    steps: list[Step]
    tier_has_llm: bool
    model: str
    seed: int | None
    plans: list[StepPlan]


def _has_code(step: Step) -> bool:
    code = step.get("code")
    return isinstance(code, str) and bool(code.strip())


def build_execution_graph(
    provider: LLMProvider, *, prompt_version: str = "v1"
) -> CompiledStateGraph[ExecutionState]:
    """Compile the EXECUTION graph bound to ``provider``."""
    from langgraph.graph import END, START, StateGraph

    system_prompt = load("translate-step", prompt_version)

    async def plan_steps(state: ExecutionState) -> ExecutionState:
        plans: list[StepPlan] = []
        for idx, step in enumerate(state.get("steps", [])):
            if _has_code(step):
                plans.append({"index": idx, "mode": "deterministic", "code": step.get("code")})
                continue
            if not state.get("tier_has_llm", False):
                plans.append({"index": idx, "mode": "error", "error": "NO_LLM_FOR_AGENTIC_STEP"})
                continue
            result = await complete_with_prompt(
                provider,
                model=state.get("model", "default"),
                system=system_prompt,
                user=str(step.get("action", "")),
                seed=state.get("seed"),
            )
            translated = parse_json_object(result.content)
            plans.append(
                {
                    "index": idx,
                    "mode": "agentic_translated",
                    "mcp_provider": step.get("mcp_provider"),
                    "tool": translated.get("tool"),
                    "arguments": translated.get("arguments", {}),
                }
            )
        return {"plans": plans}

    graph: StateGraph[ExecutionState] = StateGraph(ExecutionState)
    graph.add_node("plan_steps", plan_steps)
    graph.add_edge(START, "plan_steps")
    graph.add_edge("plan_steps", END)
    return graph.compile()
