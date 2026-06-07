"""URL semantic generator (M3-7).

Given a target URL + a natural-language intent ("checkout flow"), the LLM
decomposes the journey into FE_WEB end-to-end test cases (happy + edge). Drafts
route to ``playwright-mcp`` with agentic steps (``code=""`` translated at
execution time, M3-10) so the runner drives the browser.

This is the *semantic* counterpart to the deterministic heuristic crawler (M2-3):
the crawler BFS-fills forms blindly; here the model understands the intent and
emits journey-shaped cases. One-shot completion (not a graph). Pure orchestration
+ mapping; the caller owns provider resolution, ``AgentSession`` persistence, and
SSE streaming.
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
class UrlSemanticUsage:
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


@dataclass
class UrlSemanticResult:
    drafts: list[TestCaseDraft] = field(default_factory=list)
    usage: UrlSemanticUsage | None = None
    error: str | None = None


class UrlSemanticGenerator:
    """Drive the LLM over a URL + intent → FE_WEB journey :class:`TestCaseDraft`s."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        model: str,
        prompt_version: str = "v1",
        prompt_override: str | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._prompt_version = prompt_version
        # M5-3: resolved per-workspace fork content; None → file default.
        self._prompt_override = prompt_override

    async def run(
        self,
        url: str,
        intent: str,
        *,
        seed: int | None = None,
        max_cases: int = 20,
    ) -> UrlSemanticResult:
        """Propose journey cases for ``intent`` on ``url``. Empty intent → error."""
        if not intent.strip():
            return UrlSemanticResult(error="EMPTY_INTENT")

        template = self._prompt_override or load("generate-url-semantic", self._prompt_version)
        system = template.replace("{url}", url).replace("{intent}", intent)
        result = await complete_with_prompt(
            self._provider,
            model=self._model,
            system=system,
            user=f"Generate the test cases for: {intent}",
            seed=seed,
        )
        usage = UrlSemanticUsage(
            model=self._model,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
        )
        obj = parse_json_object(result.content)
        raws = obj.get("cases", [])
        drafts = map_raw_cases(
            raws if isinstance(raws, list) else [],
            target_kind=TargetKind.FE_WEB,
            mcp_provider="playwright-mcp",
            strategy="url-semantic",
            case_kind="url_semantic",
            tags=["ai-generated", "url-semantic"],
            max_cases=max_cases,
        )
        return UrlSemanticResult(drafts=drafts, usage=usage)
