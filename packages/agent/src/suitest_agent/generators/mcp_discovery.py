"""MCP tool-discovery generator (M3-9).

Given the persisted tool catalog of a registered MCP provider (the
``tools/list`` result captured at M2-7/M2-8 register/discover time), the LLM
explores the tools and proposes contract test cases (happy path + negative /
boundary per tool). Drafts route to the provider itself (``mcp_provider`` =
provider name) with the provider's ``target_kind``; steps are agentic
(``code=""`` translated at execution time, M3-10).

One-shot completion (not a graph). Pure orchestration + mapping; the caller owns
provider resolution, ``AgentSession`` persistence, and SSE streaming.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from suitest_agent.generators._drafts import map_raw_cases
from suitest_agent.graphs._util import complete_with_prompt, parse_json_object
from suitest_agent.prompts.loader import load

if TYPE_CHECKING:
    from suitest_shared.domain.enums import TargetKind
    from suitest_shared.schemas.generator_input import TestCaseDraft

    from suitest_agent.providers.base import LLMProvider


@dataclass(frozen=True)
class McpDiscoveryUsage:
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


@dataclass
class McpDiscoveryResult:
    drafts: list[TestCaseDraft] = field(default_factory=list)
    usage: McpDiscoveryUsage | None = None
    error: str | None = None


def _format_tools(tools: list[dict[str, object]]) -> list[str]:
    """Render each catalog tool as ``name — description (args: a, b)``."""
    lines: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "").strip()
        if not name:
            continue
        description = str(tool.get("description") or "").strip()
        schema = tool.get("input_schema")
        if not isinstance(schema, dict):
            schema = tool.get("argSchema") if isinstance(tool.get("argSchema"), dict) else {}
        props = schema.get("properties") if isinstance(schema, dict) else None
        arg_names = list(props.keys()) if isinstance(props, dict) else []
        suffix = f" (args: {', '.join(arg_names)})" if arg_names else ""
        lines.append(f"{name} — {description}{suffix}".rstrip())
    return lines


class McpDiscoveryGenerator:
    """Drive the LLM over an MCP tool catalog → contract :class:`TestCaseDraft`s."""

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
        tools: list[dict[str, object]],
        *,
        target_kind: TargetKind,
        mcp_provider_name: str,
        seed: int | None = None,
        max_cases: int = 20,
    ) -> McpDiscoveryResult:
        """Propose cases for ``tools``. Empty catalog → ``EMPTY_CATALOG`` error."""
        tool_lines = _format_tools(tools)
        if not tool_lines:
            return McpDiscoveryResult(error="EMPTY_CATALOG")

        template = self._prompt_override or load("discover-mcp-cases", self._prompt_version)
        system = template.replace("{tools}", "\n".join(tool_lines))
        result = await complete_with_prompt(
            self._provider,
            model=self._model,
            system=system,
            user="Propose the test cases now.",
            seed=seed,
        )
        usage = McpDiscoveryUsage(
            model=self._model,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
        )
        obj = parse_json_object(result.content)
        raws = obj.get("cases", [])
        drafts = map_raw_cases(
            raws if isinstance(raws, list) else [],
            target_kind=target_kind,
            mcp_provider=mcp_provider_name,
            strategy="mcp-discovery",
            case_kind="mcp_discovery",
            tags=["ai-generated", "mcp-discovery"],
            max_cases=max_cases,
        )
        return McpDiscoveryResult(drafts=drafts, usage=usage)
