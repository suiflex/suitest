"""Capability tier + autonomy resolver.

The deployment base tier is always ZERO — LLM and embeddings are NOT configured
from env. Providers are set per-workspace from the web UI (Settings → LLM
provider) and stored (AES-encrypted) in the DB; the service layer
(``CapabilityService`` / ``build_workspace_overlay``) raises the effective tier
from the workspace's active ``LLMConfig``. These resolvers only supply the ZERO
base + the pure (tier → features/autonomy) primitives the overlay builds on. See
docs/CAPABILITY_TIERS.md for the contract.
"""

from __future__ import annotations

from enum import Flag, StrEnum, auto
from typing import Final

from pydantic import BaseModel, Field


class Tier(StrEnum):
    """Capability tier. The env base is always ZERO; LOCAL/CLOUD come from the
    per-workspace LLM config (web UI)."""

    ZERO = "ZERO"
    LOCAL = "LOCAL"
    CLOUD = "CLOUD"


class TierFlag(Flag):
    """Bitwise tier requirement, used by the ``require_tier`` service decorator.

    Distinct from the ``Tier`` StrEnum: ``Tier`` is the *resolved* deployment tier
    (one value), whereas ``TierFlag`` is a *set* of acceptable tiers a feature
    permits. Use :func:`tier_in` to test membership.
    """

    ZERO = auto()
    LOCAL = auto()
    CLOUD = auto()
    ANY = ZERO | LOCAL | CLOUD


_TIER_TO_FLAG: Final[dict[Tier, TierFlag]] = {
    Tier.ZERO: TierFlag.ZERO,
    Tier.LOCAL: TierFlag.LOCAL,
    Tier.CLOUD: TierFlag.CLOUD,
}


def tier_in(t: Tier, flag: TierFlag) -> bool:
    """Return True iff the resolved ``Tier`` ``t`` is permitted by ``flag``.

    Translates the ``Tier`` StrEnum to its matching ``TierFlag`` bit, then tests
    bitwise membership. ``tier_in(Tier.ZERO, TierFlag.ANY)`` is True;
    ``tier_in(Tier.ZERO, TierFlag.CLOUD)`` is False.
    """
    return _TIER_TO_FLAG[t] in flag


class AutonomyLevel(StrEnum):
    """Workspace autonomy dial. ZERO tier is locked to MANUAL."""

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
    """Autonomy availability + default for current tier."""

    available: list[AutonomyLevel]
    default: AutonomyLevel


class CapabilitySnapshot(BaseModel):
    """Immutable view of resolved capabilities."""

    tier: Tier
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


def resolve_tier() -> Tier:
    """The env base tier is always :attr:`Tier.ZERO`.

    LLM providers are configured per-workspace from the web UI, not env, so the
    deployment-wide base is unconditionally ZERO. The effective per-workspace tier
    is raised by the service layer from the stored ``LLMConfig`` (see
    ``apps/api/.../capabilities.build_workspace_overlay`` and
    ``CapabilityService.resolve``).
    """
    return Tier.ZERO


def resolve_embeddings() -> EmbeddingsConfig:
    """Embeddings are disabled at the env base (``EmbeddingsConfig(enabled=False)``).

    Not env-configured: the semantic-search feature flag follows this base, and the
    embedder runtime (``suitest_core.embeddings.get_embedder``) is resolved
    independently. Kept as a function so the snapshot/feature builders have a stable
    seam if a workspace-driven embeddings config is added later.
    """
    return EmbeddingsConfig(enabled=False)


def compute_features(tier: Tier, embeddings: EmbeddingsConfig) -> dict[str, bool]:
    """Map (tier, embeddings) → the 13 feature flags (docs/CAPABILITY_TIERS.md §10).

    ZERO disables every ``ai_*`` flag and ``auto_defect_filing_ai``; LOCAL/CLOUD
    enable them. ``semantic_search`` tracks ``embeddings.enabled`` at any tier;
    ``fts_search`` and ``auto_defect_filing_rule`` are always on.
    """
    ai_on = tier is not Tier.ZERO
    return {
        "manual_tcm": True,
        "deterministic_runner": True,
        "deterministic_generator_openapi": True,
        "deterministic_generator_recorder": True,
        "deterministic_generator_crawler": True,
        "ai_generation": ai_on,
        "ai_execution_agentic": ai_on,
        "ai_diagnose": ai_on,
        "ai_conversation": ai_on,
        "semantic_search": embeddings.enabled,
        "fts_search": True,
        "auto_defect_filing_ai": ai_on,
        "auto_defect_filing_rule": True,
    }


def compute_autonomy(tier: Tier) -> AutonomyInfo:
    """Autonomy availability + default for ``tier`` (docs/CAPABILITY_TIERS.md §10)."""
    if tier is Tier.ZERO:
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
    """Return the ZERO base :class:`CapabilitySnapshot` (no env, no LLM).

    Retained for the service layer (``CapabilityService``), which layers the
    per-workspace overlay on top of this base. The HTTP ``/capabilities`` response
    uses the richer ``suitest_shared`` ``Capabilities`` schema assembled from the
    same primitives (:func:`resolve_tier`, :func:`resolve_embeddings`,
    :func:`compute_features`, :func:`compute_autonomy`).
    """
    tier = resolve_tier()
    embeddings_cfg = resolve_embeddings()
    return CapabilitySnapshot(
        tier=tier,
        llm=LLMInfo(),
        embeddings=EmbeddingsInfo(
            enabled=embeddings_cfg.enabled,
            backend=embeddings_cfg.backend,
            model=embeddings_cfg.model,
            dim=embeddings_cfg.dim,
        ),
        features=compute_features(tier, embeddings_cfg),
        autonomy=compute_autonomy(tier),
        mcp_providers=[],
    )
