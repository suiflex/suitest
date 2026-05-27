"""Canonical ``GET /capabilities`` response schema (docs/CAPABILITY_TIERS.md §10).

This is the ONE schema serialised by the public ``/capabilities`` endpoint. It is
assembled in the API layer from the ``suitest_core`` primitives (``resolve_tier``,
``resolve_embeddings``, ``compute_features``, ``compute_autonomy``) plus, when a
workspace context is present, an overlay of the workspace ``WorkspaceCapability``,
active ``LLMConfig``, and ``McpProvider`` rows.

The lightweight ``suitest_core.capabilities.CapabilitySnapshot`` is kept for the
internal service layer (tier + feature dict + overlay flag); this richer schema is
the wire contract. Field names mirror CAPABILITY_TIERS §10 verbatim; ``mcpProviders``
is the JSON alias for ``mcp_providers``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from suitest_shared.domain.enums import AutonomyLevel, Tier


class McpProviderPublic(BaseModel):
    """Public MCP provider entry — same shape as ``GET /mcp/providers`` rows."""

    id: str
    name: str
    kind: str
    health: str = "unknown"
    is_default: bool = Field(default=False, alias="isDefault")

    model_config = ConfigDict(populate_by_name=True)


class LLMSection(BaseModel):
    """LLM provider info. ``provider`` is ``"none"`` in ZERO tier."""

    provider: str
    model: str | None = None
    base_url: str | None = None
    is_test_provider: bool = False


class EmbeddingsSection(BaseModel):
    """Embeddings backend info (independent of LLM tier)."""

    enabled: bool
    backend: str
    model: str | None = None
    dim: int | None = None


class FeaturesSection(BaseModel):
    """The 13 capability feature flags resolved from (tier, embeddings)."""

    manual_tcm: bool
    deterministic_runner: bool
    deterministic_generator_openapi: bool
    deterministic_generator_recorder: bool
    deterministic_generator_crawler: bool
    ai_generation: bool
    ai_execution_agentic: bool
    ai_diagnose: bool
    ai_conversation: bool
    semantic_search: bool
    fts_search: bool
    auto_defect_filing_ai: bool
    auto_defect_filing_rule: bool


class AutonomySection(BaseModel):
    """Autonomy levels available + the recommended default for the tier."""

    available: list[AutonomyLevel]
    default: AutonomyLevel


class Capabilities(BaseModel):
    """Full ``GET /capabilities`` response."""

    tier: Tier
    llm: LLMSection
    embeddings: EmbeddingsSection
    features: FeaturesSection
    autonomy: AutonomySection
    version: str
    mcp_providers: list[McpProviderPublic] = Field(default_factory=list, alias="mcpProviders")
    build: str | None = None

    model_config = ConfigDict(populate_by_name=True)
