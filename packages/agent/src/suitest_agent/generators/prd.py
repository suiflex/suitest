"""PRD natural-language generator (M3-6).

Wraps the GENERATION LangGraph (:func:`build_generation_graph`): given a PRD /
user story / free text, the LLM extracts user stories and drafts happy-path +
edge/negative test cases. The graph returns minimal drafts (``title`` +
``priority`` + ``steps[action, expected]``); this module maps them to canonical
:class:`TestCaseDraft`s the API layer persists exactly like a deterministic
generator's output.

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

from suitest_shared.domain.enums import CaseSource, Priority, TargetKind
from suitest_shared.schemas.generator_input import TestCaseDraft, TestStepDraft

from suitest_agent.graphs.generation import build_generation_graph

if TYPE_CHECKING:
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
        drafts: list[TestCaseDraft] = []
        for raw in raws[:max_cases]:
            draft = self._to_draft(raw)
            if draft is not None:
                drafts.append(draft)
        return PrdResult(drafts=drafts, usage=usage)

    def _to_draft(self, raw: dict[str, object]) -> TestCaseDraft | None:
        """Map one raw LLM case dict to a TestCaseDraft; skip if unusable."""
        title = str(raw.get("title") or "").strip()
        if not title:
            return None

        steps: list[TestStepDraft] = []
        raw_steps = raw.get("steps")
        if isinstance(raw_steps, list):
            for raw_step in raw_steps:
                if not isinstance(raw_step, dict):
                    continue
                action = str(raw_step.get("action") or "").strip()
                if not action:
                    continue
                steps.append(
                    TestStepDraft(
                        order=len(steps) + 1,
                        action=action,
                        expected=str(raw_step.get("expected") or "").strip(),
                        # Agentic step: no code → translated to an MCP call at
                        # execution time (M3-10). Routes via the default provider.
                        code="",
                        mcp_provider=self._mcp,
                        target_kind=self._target_kind,
                    )
                )
        if not steps:
            return None

        return TestCaseDraft(
            name=title[:255],
            description=str(raw.get("description") or "").strip(),
            priority=_priority(raw.get("priority")),
            source=CaseSource.AI,
            target_kind=self._target_kind,
            tags=["ai-generated", "prd"],
            generated_from={"strategy": "prd-parsing", "case_kind": "prd"},
            steps=steps,
        )


def _priority(value: object) -> Priority:
    """Coerce a raw priority value to a :class:`Priority`; default ``P2``."""
    try:
        return Priority(str(value).strip().upper())
    except ValueError:
        return Priority.P2
