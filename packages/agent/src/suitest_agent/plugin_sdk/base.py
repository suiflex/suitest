"""AgentPluginBase — abstract base class and YAML spec for M8 custom agent plugins.

Every custom agent must:
  1. Define a class-level ``spec: AgentPluginSpec`` describing identity/config.
  2. Implement ``build_context`` to inject extra context into the LLM system prompt.

Plugin classes are discovered at startup via the ``suitest.plugins`` Python entry
point group (see :mod:`suitest_agent.plugin_sdk.loader`) and registered in
:data:`suitest_agent.plugin_sdk.registry.PLUGIN_REGISTRY`.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_VALID_TIERS = frozenset({"ZERO", "LOCAL", "CLOUD"})


class AgentPluginSpec(BaseModel):
    """YAML-serialisable descriptor for a custom agent plugin (M8-1).

    ``name`` must be a valid slug (kebab-case, no spaces) and unique within the
    workspace. ``requires_tier`` gates which deployments may activate this plugin.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(
        description="Unique slug (kebab-case). Used as the lookup key in the registry.",
    )
    version: str = Field(
        description="SemVer string, e.g. '1.0.0'.",
    )
    display_name: str = Field(
        description="Human-readable label shown in the UI.",
    )
    description: str = Field(
        description="Short explanation of what this agent does.",
    )
    system_prompt: str = Field(
        max_length=4000,
        description="System prompt injected ahead of the user turn. Max 4000 chars.",
    )
    tool_whitelist: list[str] = Field(
        default_factory=list,
        description=(
            "MCP tool names this agent may call (e.g. 'playwright_mcp.navigate'). "
            "Empty list means all tools are permitted."
        ),
    )
    model_preference: str | None = Field(
        default=None,
        description=(
            "LiteLLM model string (e.g. 'claude-sonnet-4-6'). "
            "None falls back to the workspace default."
        ),
    )
    target_kind_filter: list[str] = Field(
        default_factory=list,
        description=(
            "TargetKind values this agent handles (e.g. ['BE_REST', 'FE_WEB']). "
            "Empty list means the agent handles all target kinds."
        ),
    )
    requires_tier: str = Field(
        default="ZERO",
        description="Minimum tier required to activate. One of: 'ZERO', 'LOCAL', 'CLOUD'.",
    )
    author: str | None = Field(default=None, description="Plugin author name or email.")
    homepage: str | None = Field(default=None, description="URL to plugin docs / repo.")

    @field_validator("requires_tier")
    @classmethod
    def _validate_tier(cls, v: str) -> str:
        if v not in _VALID_TIERS:
            raise ValueError(f"requires_tier must be one of {sorted(_VALID_TIERS)}, got {v!r}")
        return v

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                f"name must be kebab-case (lowercase letters, digits, hyphens), got {v!r}"
            )
        return v


class AgentPluginBase(ABC):
    """Abstract base class every custom agent plugin must inherit from.

    Subclasses MUST set a class-level ``spec: AgentPluginSpec``.  The loader
    validates this at discovery time and skips classes that do not conform.

    Example::

        class MyAgent(AgentPluginBase):
            spec = AgentPluginSpec(
                name="my-agent",
                version="1.0.0",
                display_name="My Agent",
                description="Does something useful.",
                system_prompt="You are a helpful agent...",
            )

            async def build_context(self, test_case_id: str, step_index: int) -> dict[str, object]:
                return {"extra_hint": "look for XSS patterns"}
    """

    spec: AgentPluginSpec  # class-level; concrete subclasses must set this

    @abstractmethod
    async def build_context(self, test_case_id: str, step_index: int) -> dict[str, object]:
        """Return extra context injected into the LLM system prompt.

        The returned dict is serialised to JSON and appended to the system prompt
        as a ``<context>`` block before the user turn.

        Args:
            test_case_id: The ID of the test case being executed.
            step_index: Zero-based index of the step within the test case.

        Returns:
            A JSON-serialisable dict of context entries.
        """
