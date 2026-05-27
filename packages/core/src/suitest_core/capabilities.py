"""Capability tier + autonomy resolver.

Reads env once at call time. Callers should cache the resulting snapshot for the
lifetime of the process. See docs/CAPABILITY_TIERS.md for the contract.
"""

from __future__ import annotations

import os
from enum import Flag, StrEnum, auto
from typing import Final

from pydantic import BaseModel, Field

LOCAL_PROVIDERS: Final[frozenset[str]] = frozenset({"ollama", "llamacpp", "vllm", "lmstudio"})
CLOUD_PROVIDERS: Final[frozenset[str]] = frozenset(
    {
        "anthropic",
        "openai",
        "gemini",
        "groq",
        "openrouter",
        "azure",
        "bedrock",
        "vertex",
        "deepseek",
        "mock",
    }
)
ZERO_SENTINELS: Final[frozenset[str]] = frozenset({"", "none", "disabled"})


class ConfigError(Exception):
    """Raised when env capability config is internally inconsistent.

    e.g. a LOCAL provider with no ``SUITEST_LLM_BASE_URL``, or a key-requiring
    CLOUD provider with no ``SUITEST_LLM_API_KEY``. Surfaced at process startup so
    a misconfigured deployment fails fast (the app does not boot) rather than
    silently degrading to a wrong tier.
    """


# CLOUD providers that authenticate via IAM / service-account / canned creds and
# therefore do NOT require SUITEST_LLM_API_KEY.
_KEYLESS_CLOUD_PROVIDERS: Final[frozenset[str]] = frozenset({"bedrock", "vertex", "mock"})


class Tier(StrEnum):
    """Capability tier resolved from env."""

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


def _read_provider() -> str:
    raw = os.getenv("SUITEST_LLM_PROVIDER") or ""
    return raw.strip().lower()


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
    """Pure function: env → :class:`Tier`, strict per docs/CAPABILITY_TIERS.md §3.

    Raises :class:`ConfigError` when the provider is set but its required companion
    env var is missing (LOCAL needs ``SUITEST_LLM_BASE_URL``; key-requiring CLOUD
    providers need ``SUITEST_LLM_API_KEY``) or when the provider is unknown. No
    provider (or ``none`` / ``disabled``) resolves to ZERO and never raises, so the
    default boot stays clean.
    """
    provider = _read_provider()
    if provider in ZERO_SENTINELS:
        return Tier.ZERO

    if provider in LOCAL_PROVIDERS:
        if not os.getenv("SUITEST_LLM_BASE_URL"):
            raise ConfigError("LOCAL tier requires SUITEST_LLM_BASE_URL")
        return Tier.LOCAL

    if provider in CLOUD_PROVIDERS:
        if provider not in _KEYLESS_CLOUD_PROVIDERS and not os.getenv("SUITEST_LLM_API_KEY"):
            raise ConfigError(f"CLOUD provider {provider} requires SUITEST_LLM_API_KEY")
        return Tier.CLOUD

    raise ConfigError(f"Unknown SUITEST_LLM_PROVIDER: {provider}")


def resolve_embeddings() -> EmbeddingsConfig:
    """Resolve ``SUITEST_EMBEDDINGS_BACKEND`` → :class:`EmbeddingsConfig` (§3).

    Backends: ``none`` (disabled), ``fastembed`` (dim 384), ``openai`` (dim 1536),
    ``cohere`` (dim 1024). Unknown backend raises :class:`ConfigError`.
    """
    backend = (os.getenv("SUITEST_EMBEDDINGS_BACKEND") or "none").strip().lower()
    if backend == "none":
        return EmbeddingsConfig(enabled=False)
    if backend == "fastembed":
        return EmbeddingsConfig(
            enabled=True,
            backend="fastembed",
            model=os.getenv("SUITEST_EMBEDDINGS_MODEL") or "BAAI/bge-small-en-v1.5",
            dim=384,
        )
    if backend == "openai":
        return EmbeddingsConfig(
            enabled=True,
            backend="openai",
            model=os.getenv("SUITEST_EMBEDDINGS_MODEL") or "text-embedding-3-small",
            dim=1536,
        )
    if backend == "cohere":
        return EmbeddingsConfig(
            enabled=True,
            backend="cohere",
            model=os.getenv("SUITEST_EMBEDDINGS_MODEL") or "embed-english-v3.0",
            dim=1024,
        )
    raise ConfigError(f"Unknown SUITEST_EMBEDDINGS_BACKEND: {backend}")


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
    """Return a fully-populated :class:`CapabilitySnapshot` from current env.

    Retained for the service layer (``CapabilityService``), which works with the
    lightweight snapshot + workspace overlay. The HTTP ``/capabilities`` response
    uses the richer ``suitest_shared`` ``Capabilities`` schema assembled from the
    same primitives (:func:`resolve_tier`, :func:`resolve_embeddings`,
    :func:`compute_features`, :func:`compute_autonomy`).
    """
    tier = resolve_tier()
    provider = _read_provider()
    resolved_provider = provider if tier is not Tier.ZERO else None
    embeddings_cfg = resolve_embeddings()
    llm = LLMInfo(
        provider=resolved_provider,
        model=os.getenv("SUITEST_LLM_MODEL") or None,
        base_url=os.getenv("SUITEST_LLM_BASE_URL") or None,
        is_test_provider=resolved_provider == "mock",
    )
    return CapabilitySnapshot(
        tier=tier,
        llm=llm,
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
