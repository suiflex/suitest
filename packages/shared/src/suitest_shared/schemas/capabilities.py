"""Canonical ``GET /capabilities`` response schema.

This is the ONE schema serialised by the public ``/capabilities`` endpoint. It is
assembled in the API layer from the ``suitest_core`` readiness primitives plus, when a
workspace context is present, an overlay of the workspace ``WorkspaceCapability``,
active ``LLMConfig``, and ``McpProvider`` rows.

The lightweight ``suitest_core.capabilities.CapabilitySnapshot`` is kept for the
internal service layer; this richer schema is the wire contract. ``mcpProviders``
is the JSON alias for ``mcp_providers``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from suitest_shared.domain.enums import AutonomyLevel, LlmStatus


class McpProviderPublic(BaseModel):
    """Public MCP provider entry — same shape as ``GET /mcp/providers`` rows."""

    id: str
    name: str
    kind: str
    health: str = "unknown"
    is_default: bool = Field(default=False, alias="isDefault")

    model_config = ConfigDict(populate_by_name=True)


class LLMSection(BaseModel):
    """Workspace LLM provider and readiness."""

    status: LlmStatus = LlmStatus.NOT_CONFIGURED
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    is_test_provider: bool = False


class EmbeddingsSection(BaseModel):
    """Embeddings backend info (independent of LLM readiness)."""

    enabled: bool
    backend: str
    model: str | None = None
    dim: int | None = None


class FeaturesSection(BaseModel):
    """The 13 capability feature flags resolved from readiness and embeddings."""

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
    """Autonomy levels available plus the recommended default."""

    available: list[AutonomyLevel]
    default: AutonomyLevel


class AuthSection(BaseModel):
    """Auth-related capability flags resolved from process settings (M1e).

    ``google_oauth_enabled`` is ``True`` only when BOTH the Google OAuth client id
    and client secret are configured; the login page renders the Google button
    solely off this flag.
    """

    google_oauth_enabled: bool = False


class Capabilities(BaseModel):
    """Full ``GET /capabilities`` response."""

    llm: LLMSection
    embeddings: EmbeddingsSection
    features: FeaturesSection
    autonomy: AutonomySection
    auth: AuthSection = Field(default_factory=AuthSection)
    version: str
    mcp_providers: list[McpProviderPublic] = Field(default_factory=list, alias="mcpProviders")
    build: str | None = None

    model_config = ConfigDict(populate_by_name=True)
