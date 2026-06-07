"""GENERATION mode graph (M3-4, docs/AI_AGENT.md §4.1).

classify_input → draft_cases (LLM) → parse_drafts → END.

Produces DRAFT test cases from free text / a PRD. Persistence + SSE emission are
the API layer's job; this graph returns the parsed drafts in state so the caller
streams + stores them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from suitest_agent.graphs._util import complete_with_prompt, parse_json_object
from suitest_agent.prompts.loader import load

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from suitest_agent.providers.base import LLMProvider


class GenerationState(TypedDict, total=False):
    workspace_id: str
    input_text: str
    model: str
    seed: int | None
    raw_output: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    draft_cases: list[dict[str, object]]
    error: str | None


def build_generation_graph(
    provider: LLMProvider, *, prompt_version: str = "v1", prompt_override: str | None = None
) -> CompiledStateGraph[GenerationState]:
    """Compile the GENERATION graph bound to ``provider``.

    ``prompt_override`` (M5-3) injects a resolved per-workspace prompt fork; when
    ``None`` the file default ``generate-from-prd`` is loaded as before.
    """
    from langgraph.graph import END, START, StateGraph

    system_prompt = prompt_override or load("generate-from-prd", prompt_version)

    async def classify_input(state: GenerationState) -> GenerationState:
        text = state.get("input_text", "").strip()
        return {"error": None if text else "EMPTY_INPUT"}

    async def draft_cases(state: GenerationState) -> GenerationState:
        if state.get("error"):
            return {"raw_output": ""}
        result = await complete_with_prompt(
            provider,
            model=state.get("model", "default"),
            system=system_prompt,
            user=state["input_text"],
            seed=state.get("seed"),
        )
        return {
            "raw_output": result.content,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
            "cost_usd": result.cost_usd,
        }

    async def parse_drafts(state: GenerationState) -> GenerationState:
        if state.get("error"):
            return {"draft_cases": []}
        obj = parse_json_object(state.get("raw_output", ""))
        cases = obj.get("cases", [])
        cases_list = cases if isinstance(cases, list) else []
        clean: list[dict[str, object]] = [c for c in cases_list if isinstance(c, dict)]
        return {"draft_cases": clean}

    graph: StateGraph[GenerationState] = StateGraph(GenerationState)
    graph.add_node("classify_input", classify_input)
    graph.add_node("draft_cases", draft_cases)
    graph.add_node("parse_drafts", parse_drafts)
    graph.add_edge(START, "classify_input")
    graph.add_edge("classify_input", "draft_cases")
    graph.add_edge("draft_cases", "parse_drafts")
    graph.add_edge("parse_drafts", END)
    return graph.compile()
