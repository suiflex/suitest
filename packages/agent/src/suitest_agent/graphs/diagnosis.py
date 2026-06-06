"""DIAGNOSIS mode graph (M3-4, docs/AI_AGENT.md §4.5 + §10).

gather_context → classify_category (LLM) → structured :class:`Diagnosis` → END.

Replaces the ZERO-tier ``MANUAL_TRIAGE`` rule fallback with an LLM root-cause
classification. Output is validated into a Pydantic model; an unparseable or
out-of-enum response degrades safely to ``MANUAL_TRIAGE`` with confidence 0.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypedDict

from pydantic import BaseModel, Field, ValidationError

from suitest_agent.graphs._util import complete_with_prompt, parse_json_object
from suitest_agent.prompts.loader import load

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from suitest_agent.providers.base import LLMProvider

DiagnosisCategory = Literal["REGRESSION", "FLAKE", "INFRA", "SPEC_DRIFT", "MANUAL_TRIAGE"]


class Diagnosis(BaseModel):
    """Structured diagnosis output (docs/AI_AGENT.md §10)."""

    category: DiagnosisCategory
    confidence: float = Field(ge=0.0, le=1.0)
    root_cause: str = Field(max_length=400)
    suggested_fix: str | None = None
    rerun_recommended: bool = False


_FALLBACK = Diagnosis(
    category="MANUAL_TRIAGE",
    confidence=0.0,
    root_cause="Insufficient or unparseable evidence; manual triage required.",
)


class DiagnosisState(TypedDict, total=False):
    run_id: str
    evidence: str
    model: str
    seed: int | None
    diagnosis: Diagnosis


def build_diagnosis_graph(
    provider: LLMProvider, *, prompt_version: str = "v1"
) -> CompiledStateGraph[DiagnosisState]:
    """Compile the DIAGNOSIS graph bound to ``provider``."""
    from langgraph.graph import END, START, StateGraph

    system_prompt = load("diagnose-failure", prompt_version)

    async def gather_context(state: DiagnosisState) -> DiagnosisState:
        # Evidence is assembled by the caller (logs + commits + history); here we
        # only ensure a non-empty string reaches the classifier.
        return {"evidence": state.get("evidence", "").strip()}

    async def classify_category(state: DiagnosisState) -> DiagnosisState:
        evidence = state.get("evidence", "")
        if not evidence:
            return {"diagnosis": _FALLBACK}
        result = await complete_with_prompt(
            provider,
            model=state.get("model", "default"),
            system=system_prompt,
            user=evidence,
            seed=state.get("seed"),
        )
        obj = parse_json_object(result.content)
        try:
            diagnosis = Diagnosis.model_validate(obj)
        except ValidationError:
            diagnosis = _FALLBACK
        return {"diagnosis": diagnosis}

    graph: StateGraph[DiagnosisState] = StateGraph(DiagnosisState)
    graph.add_node("gather_context", gather_context)
    graph.add_node("classify_category", classify_category)
    graph.add_edge(START, "gather_context")
    graph.add_edge("gather_context", "classify_category")
    graph.add_edge("classify_category", END)
    return graph.compile()
