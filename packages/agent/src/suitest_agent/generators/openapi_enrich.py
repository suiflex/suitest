"""OpenAPI edge-case enricher (M3-8).

The deterministic :class:`OpenApiGenerator` owns the contract suite; this adds an
*optional* LLM pass that proposes boundary / fuzz / negative edge cases on top.
It is enrichment — never required: the caller only invokes it when the workspace
has an active LLM, and a failure degrades to "deterministic-only" rather than
failing the whole generation (ZERO-first).

One-shot completion (not a graph): the operation list is fed to the
``enrich-openapi-edges`` prompt and the returned ``{cases:[...]}`` JSON is mapped
to canonical drafts via :func:`map_raw_cases`. Drafts are BE_REST / agentic
(``code=""`` translated at execution time, M3-10).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from suitest_shared.domain.enums import TargetKind

from suitest_agent.generators._drafts import map_raw_cases
from suitest_agent.graphs._util import complete_with_prompt, parse_json_object
from suitest_agent.prompts.loader import load

if TYPE_CHECKING:
    from suitest_shared.schemas.generator_input import TestCaseDraft

    from suitest_agent.providers.base import LLMProvider


@dataclass(frozen=True)
class EnrichUsage:
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


@dataclass
class EnrichResult:
    drafts: list[TestCaseDraft] = field(default_factory=list)
    usage: EnrichUsage | None = None
    error: str | None = None


class OpenApiEnricher:
    """Propose extra edge cases for a set of OpenAPI operations via the LLM."""

    def __init__(self, provider: LLMProvider, *, model: str, prompt_version: str = "v1") -> None:
        self._provider = provider
        self._model = model
        self._prompt_version = prompt_version

    async def enrich(
        self, op_summaries: list[str], *, seed: int | None = None, max_cases: int = 20
    ) -> EnrichResult:
        """Return edge-case drafts for ``op_summaries`` (empty list → no cases)."""
        if not op_summaries:
            return EnrichResult(usage=EnrichUsage(model=self._model))

        template = load("enrich-openapi-edges", self._prompt_version)
        system = template.replace("{operations}", "\n".join(op_summaries))
        result = await complete_with_prompt(
            self._provider,
            model=self._model,
            system=system,
            user="Propose the edge cases now.",
            seed=seed,
        )
        usage = EnrichUsage(
            model=self._model,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
        )
        obj = parse_json_object(result.content)
        raws = obj.get("cases", [])
        drafts = map_raw_cases(
            raws if isinstance(raws, list) else [],
            target_kind=TargetKind.BE_REST,
            mcp_provider="api-http-mcp",
            strategy="openapi-llm-edge",
            case_kind="llm_edge",
            tags=["ai-generated", "edge-case"],
            max_cases=max_cases,
        )
        return EnrichResult(drafts=drafts, usage=usage)
