"""Capability tier resolver tests."""

import pytest
from suitest_core.capabilities import (
    AutonomyLevel,
    Tier,
    TierFlag,
    resolve_capabilities,
    resolve_tier,
    tier_in,
)


def test_resolve_tier_defaults_to_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset env → ZERO tier."""
    monkeypatch.delenv("SUITEST_LLM_PROVIDER", raising=False)
    assert resolve_tier() is Tier.ZERO


def test_resolve_tier_explicit_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """`none` literal → ZERO tier."""
    monkeypatch.setenv("SUITEST_LLM_PROVIDER", "none")
    assert resolve_tier() is Tier.ZERO


def test_resolve_tier_ollama_is_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ollama` → LOCAL tier."""
    monkeypatch.setenv("SUITEST_LLM_PROVIDER", "ollama")
    assert resolve_tier() is Tier.LOCAL


def test_resolve_tier_anthropic_is_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    """`anthropic` → CLOUD tier."""
    monkeypatch.setenv("SUITEST_LLM_PROVIDER", "anthropic")
    assert resolve_tier() is Tier.CLOUD


def test_resolve_capabilities_zero_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """ZERO snapshot has AI features OFF and autonomy=['manual']."""
    monkeypatch.delenv("SUITEST_LLM_PROVIDER", raising=False)
    snap = resolve_capabilities()
    assert snap.tier is Tier.ZERO
    assert snap.llm.provider is None
    assert snap.features["ai_generation"] is False
    assert snap.features["manual_tcm"] is True
    assert snap.autonomy.available == [AutonomyLevel.MANUAL]
    assert snap.autonomy.default is AutonomyLevel.MANUAL


def test_capability_snapshot_serialises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pydantic snapshot can be model_dump()'d."""
    monkeypatch.delenv("SUITEST_LLM_PROVIDER", raising=False)
    snap = resolve_capabilities()
    payload = snap.model_dump(mode="json")
    assert payload["tier"] == "ZERO"
    assert payload["autonomy"]["default"] == "manual"


def test_tier_in_any_accepts_every_tier() -> None:
    """ANY permits every resolved tier."""
    assert tier_in(Tier.ZERO, TierFlag.ANY) is True
    assert tier_in(Tier.LOCAL, TierFlag.ANY) is True
    assert tier_in(Tier.CLOUD, TierFlag.ANY) is True


def test_tier_in_cloud_rejects_zero() -> None:
    """CLOUD-only flag excludes ZERO and LOCAL."""
    assert tier_in(Tier.ZERO, TierFlag.CLOUD) is False
    assert tier_in(Tier.LOCAL, TierFlag.CLOUD) is False
    assert tier_in(Tier.CLOUD, TierFlag.CLOUD) is True


def test_tier_in_combined_flag() -> None:
    """LOCAL | CLOUD permits both LLM tiers but not ZERO."""
    flag = TierFlag.LOCAL | TierFlag.CLOUD
    assert tier_in(Tier.ZERO, flag) is False
    assert tier_in(Tier.LOCAL, flag) is True
    assert tier_in(Tier.CLOUD, flag) is True
