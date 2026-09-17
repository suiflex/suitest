"""Workspace capability and LLM-readiness primitives."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class LlmStatus(StrEnum):
    """Readiness of the workspace's active LLM configuration."""

    NOT_CONFIGURED = "not_configured"
    VALIDATION_REQUIRED = "validation_required"
    READY = "ready"


class AutonomyLevel(StrEnum):
    """Workspace autonomy dial. A workspace without a ready LLM is manual."""

    MANUAL = "manual"
    ASSIST = "assist"
    SEMI_AUTO = "semi_auto"
    AUTO = "auto"


class LLMInfo(BaseModel):
    """LLM provider info exposed via /capabilities."""

    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    is_test_provider: bool = False
    status: LlmStatus = LlmStatus.NOT_CONFIGURED


class McpProviderInfo(BaseModel):
    """MCP provider entry in capability snapshot."""

    id: str
    name: str
    kind: str
    health: str = "unknown"
    is_default: bool = False


class EmbeddingsInfo(BaseModel):
    """Embeddings backend info exposed via /capabilities."""

    enabled: bool = False
    backend: str = "none"
    model: str | None = None
    dim: int | None = None


class AutonomyInfo(BaseModel):
    """Autonomy availability + default for current LLM readiness."""

    available: list[AutonomyLevel]
    default: AutonomyLevel


class CapabilitySnapshot(BaseModel):
    """Immutable view of resolved capabilities."""

    llm: LLMInfo = Field(default_factory=LLMInfo)
    embeddings: EmbeddingsInfo = Field(default_factory=EmbeddingsInfo)
    features: dict[str, bool]
    autonomy: AutonomyInfo
    mcp_providers: list[McpProviderInfo] = Field(default_factory=list)
    version: str = "0.1.0"


class EmbeddingsConfig(BaseModel):
    """Resolved embeddings backend config (independent of the LLM tier).

    ``dim`` is the vector dimension fixed at Alembic migration time and used to
    size ``document_chunk.embedding``. See docs/CAPABILITY_TIERS.md §5.
    """

    enabled: bool = False
    backend: str = "none"
    model: str | None = None
    dim: int | None = None


def resolve_embeddings() -> EmbeddingsConfig:
    """Embeddings are disabled at the env base (``EmbeddingsConfig(enabled=False)``).

    Not env-configured: the semantic-search feature flag follows this base, and the
    embedder runtime (``suitest_core.embeddings.get_embedder``) is resolved
    independently. Kept as a function so the snapshot/feature builders have a stable
    seam if a workspace-driven embeddings config is added later.
    """
    return EmbeddingsConfig(enabled=False)


def compute_features(llm_ready: bool, embeddings: EmbeddingsConfig) -> dict[str, bool]:
    """Build feature flags from workspace LLM readiness and embeddings."""
    return {
        "manual_tcm": True,
        "deterministic_runner": llm_ready,
        "deterministic_generator_openapi": True,
        "deterministic_generator_recorder": llm_ready,
        "deterministic_generator_crawler": llm_ready,
        "ai_generation": llm_ready,
        "ai_execution_agentic": llm_ready,
        "ai_diagnose": llm_ready,
        "ai_conversation": llm_ready,
        "semantic_search": embeddings.enabled,
        "fts_search": True,
        "auto_defect_filing_ai": llm_ready,
        "auto_defect_filing_rule": True,
    }


def compute_autonomy(llm_ready: bool) -> AutonomyInfo:
    """Return autonomy choices for the current LLM readiness."""
    if not llm_ready:
        return AutonomyInfo(available=[AutonomyLevel.MANUAL], default=AutonomyLevel.MANUAL)
    return AutonomyInfo(
        available=[
            AutonomyLevel.MANUAL,
            AutonomyLevel.ASSIST,
            AutonomyLevel.SEMI_AUTO,
            AutonomyLevel.AUTO,
        ],
        default=AutonomyLevel.ASSIST,
    )


def resolve_capabilities() -> CapabilitySnapshot:
    """Return the deployment base with no workspace LLM configured."""
    embeddings_cfg = resolve_embeddings()
    return CapabilitySnapshot(
        llm=LLMInfo(),
        embeddings=EmbeddingsInfo(
            enabled=embeddings_cfg.enabled,
            backend=embeddings_cfg.backend,
            model=embeddings_cfg.model,
            dim=embeddings_cfg.dim,
        ),
        features=compute_features(False, embeddings_cfg),
        autonomy=compute_autonomy(False),
        mcp_providers=[],
    )
