"""Capability tier + autonomy resolver.

Reads env once at call time. Callers should cache the resulting snapshot for the
lifetime of the process. See docs/CAPABILITY_TIERS.md for the contract.
"""

from __future__ import annotations

import os
from enum import StrEnum
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


class Tier(StrEnum):
    """Capability tier resolved from env."""

    ZERO = "ZERO"
    LOCAL = "LOCAL"
    CLOUD = "CLOUD"


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


def resolve_tier() -> Tier:
    """Pure function: env → Tier. Does not raise for missing keys at M0 (relaxed).

    M0 does NOT validate `SUITEST_LLM_API_KEY` or `SUITEST_LLM_BASE_URL` presence —
    that validation lands in M3 when LiteLLM wiring goes live. This stub only
    maps provider strings to tiers.
    """
    provider = _read_provider()
    if provider in ZERO_SENTINELS:
        return Tier.ZERO
    if provider in LOCAL_PROVIDERS:
        return Tier.LOCAL
    if provider in CLOUD_PROVIDERS:
        return Tier.CLOUD
    # Unknown provider in M0 → treat as ZERO + log; strict validation comes in M3.
    return Tier.ZERO


def _features_for(tier: Tier) -> dict[str, bool]:
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
        "semantic_search": False,  # depends on embeddings backend, see M4
        "fts_search": True,
        "auto_defect_filing_ai": ai_on,
        "auto_defect_filing_rule": True,
    }


def _autonomy_for(tier: Tier) -> AutonomyInfo:
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
    """Return a fully-populated CapabilitySnapshot from current env."""
    tier = resolve_tier()
    provider = _read_provider()
    resolved_provider = provider if tier is not Tier.ZERO else None
    llm = LLMInfo(
        provider=resolved_provider,
        model=os.getenv("SUITEST_LLM_MODEL") or None,
        base_url=os.getenv("SUITEST_LLM_BASE_URL") or None,
        is_test_provider=resolved_provider == "mock",
    )
    autonomy = _autonomy_for(tier)
    return CapabilitySnapshot(
        tier=tier,
        llm=llm,
        embeddings=EmbeddingsInfo(),
        features=_features_for(tier),
        autonomy=autonomy,
        mcp_providers=[],
    )
