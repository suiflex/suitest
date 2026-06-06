"""PRD natural-language generator (M3-6).

Wraps the GENERATION LangGraph (:func:`build_generation_graph`): given a PRD /
user story / free text, the LLM extracts user stories and drafts happy-path +
edge/negative test cases. The graph returns minimal drafts (``title`` +
``priority`` + ``steps[action, expected]``); :func:`map_raw_cases` maps them to
canonical :class:`TestCaseDraft`s the API layer persists exactly like a
deterministic generator's output.

Steps carry NO executable ``code`` — they are *agentic* steps whose ``action`` is
translated to an MCP call at execution time (M3-10). ``mcp_provider`` /
``target_kind`` default from the request's ``default_target_kind`` so a generated
case still routes deterministically before any translation.

LLM-driven → CLOUD/LOCAL only. The caller resolves the provider from the
workspace's active ``LLMConfig`` and owns reproducibility/cost persistence
(``AgentSession``); this module is pure orchestration + mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from suitest_shared.domain.enums import TargetKind

from suitest_agent.generators._drafts import map_raw_cases
from suitest_agent.graphs.generation import build_generation_graph

if TYPE_CHECKING:
    from suitest_shared.schemas.generator_input import TestCaseDraft

    from suitest_agent.providers.base import LLMProvider

# Canonical TargetKind → bundled MCP provider routing (mirrors the classifier's
# per-kind recommendations). A PRD case routes here before M3-10 translation.
_MCP_BY_TARGET: dict[TargetKind, str] = {
    TargetKind.BE_REST: "api-http-mcp",
    TargetKind.BE_GRAPHQL: "graphql-mcp",
    TargetKind.BE_GRPC: "grpc-mcp",
    TargetKind.FE_WEB: "playwright-mcp",
    TargetKind.FE_MOBILE: "appium-mcp",
    TargetKind.DATA: "postgres-mcp",
    TargetKind.INFRA: "kubernetes-mcp",
    TargetKind.CUSTOM: "playwright-mcp",
}


def mcp_for_target_kind(target_kind: TargetKind) -> str:
    """Return the default bundled MCP provider name for ``target_kind``."""
    return _MCP_BY_TARGET.get(target_kind, "playwright-mcp")


@dataclass(frozen=True)
class PrdUsage:
    """Token + cost rollup for the single GENERATION completion (M3-5/M3-14)."""

    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


@dataclass
class PrdResult:
    """Outcome of one PRD generation: mapped drafts + usage (or an error code)."""

    drafts: list[TestCaseDraft] = field(default_factory=list)
    usage: PrdUsage | None = None
    error: str | None = None


class PrdGenerator:
    """Drive the GENERATION graph and map raw drafts → :class:`TestCaseDraft`."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        model: str,
        default_target_kind: TargetKind = TargetKind.CUSTOM,
        prompt_version: str = "v1",
    ) -> None:
        self._provider = provider
        self._model = model
        self._target_kind = default_target_kind
        self._mcp = mcp_for_target_kind(default_target_kind)
        self._prompt_version = prompt_version

    async def run(
        self, prd_text: str, *, seed: int | None = None, max_cases: int = 20
    ) -> PrdResult:
        """Generate drafts from ``prd_text``. Empty input → ``EMPTY_INPUT`` error."""
        graph = build_generation_graph(self._provider, prompt_version=self._prompt_version)
        state = await graph.ainvoke({"input_text": prd_text, "model": self._model, "seed": seed})
        if state.get("error"):
            return PrdResult(error=str(state["error"]))

        usage = PrdUsage(
            model=self._model,
            tokens_in=int(state.get("tokens_in", 0) or 0),
            tokens_out=int(state.get("tokens_out", 0) or 0),
            cost_usd=float(state.get("cost_usd", 0.0) or 0.0),
        )
        raws = state.get("draft_cases", [])
        drafts = map_raw_cases(
            raws if isinstance(raws, list) else [],
            target_kind=self._target_kind,
            mcp_provider=self._mcp,
            strategy="prd-parsing",
            case_kind="prd",
            tags=["ai-generated", "prd"],
            max_cases=max_cases,
        )
        return PrdResult(drafts=drafts, usage=usage)
