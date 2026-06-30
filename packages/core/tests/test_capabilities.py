"""Capability tier resolver tests.

Post-cabut contract: LLM/embeddings are configured per-workspace from the web UI,
not env, so the resolvers are env-independent — the deployment base is always ZERO
with embeddings disabled. The effective per-workspace tier is raised by the service
layer (``CapabilityService`` / ``build_workspace_overlay``) from the stored
``LLMConfig`` via the pure ``compute_features`` / ``compute_autonomy`` primitives,
which these tests also lock.
"""

import pytest
from suitest_core.capabilities import (
    AutonomyLevel,
    Tier,
    TierFlag,
    compute_autonomy,
    compute_features,
    resolve_capabilities,
    resolve_embeddings,
    resolve_tier,
    tier_in,
)


def test_resolve_tier_always_zero() -> None:
    """The env base tier is unconditionally ZERO."""
    assert resolve_tier() is Tier.ZERO


def test_resolve_tier_ignores_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cabut: ``SUITEST_LLM_*`` env is inert — even a full CLOUD config → ZERO."""
    monkeypatch.setenv("SUITEST_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("SUITEST_LLM_API_KEY", "sk-x")
    monkeypatch.setenv("SUITEST_LLM_BASE_URL", "http://should-be-ignored")
    monkeypatch.setenv("SUITEST_LLM_MODEL", "claude-sonnet-4-5")
    assert resolve_tier() is Tier.ZERO


def test_resolve_embeddings_always_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Embeddings base is disabled regardless of ``SUITEST_EMBEDDINGS_*`` env."""
    assert resolve_embeddings().enabled is False

    monkeypatch.setenv("SUITEST_EMBEDDINGS_BACKEND", "fastembed")
    monkeypatch.setenv("SUITEST_EMBEDDINGS_MODEL", "BAAI/bge-small-en-v1.5")
    cfg = resolve_embeddings()
    assert cfg.enabled is False
    assert cfg.backend == "none"
    assert cfg.dim is None


def test_resolve_capabilities_zero_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """The base snapshot has no LLM, AI features OFF, autonomy=['manual']."""
    monkeypatch.setenv("SUITEST_LLM_PROVIDER", "anthropic")  # still ignored
    snap = resolve_capabilities()
    assert snap.tier is Tier.ZERO
    assert snap.llm.provider is None
    assert snap.embeddings.enabled is False
    assert snap.features["ai_generation"] is False
    assert snap.features["semantic_search"] is False
    assert snap.features["manual_tcm"] is True
    assert snap.autonomy.available == [AutonomyLevel.MANUAL]
    assert snap.autonomy.default is AutonomyLevel.MANUAL


def test_capability_snapshot_serialises() -> None:
    """Pydantic snapshot can be model_dump()'d."""
    snap = resolve_capabilities()
    payload = snap.model_dump(mode="json")
    assert payload["tier"] == "ZERO"
    assert payload["autonomy"]["default"] == "manual"


def test_compute_features_zero_disables_ai() -> None:
    """ZERO tier turns every ``ai_*`` flag off; deterministic flags stay on."""
    embeddings = resolve_embeddings()
    features = compute_features(Tier.ZERO, embeddings)
    assert features["ai_generation"] is False
    assert features["ai_diagnose"] is False
    assert features["semantic_search"] is False
    assert features["manual_tcm"] is True
    assert features["deterministic_runner"] is True
    assert features["fts_search"] is True


def test_compute_features_cloud_enables_ai() -> None:
    """The overlay raises tier → CLOUD; the primitive must then enable AI flags."""
    embeddings = resolve_embeddings()
    features = compute_features(Tier.CLOUD, embeddings)
    assert features["ai_generation"] is True
    assert features["ai_execution_agentic"] is True
    assert features["ai_diagnose"] is True
    assert features["ai_conversation"] is True
    # embeddings still disabled at base → semantic_search tracks it, not the tier.
    assert features["semantic_search"] is False


def test_compute_autonomy_by_tier() -> None:
    """ZERO is locked to MANUAL; LLM tiers expose the full dial (default ASSIST)."""
    zero = compute_autonomy(Tier.ZERO)
    assert zero.available == [AutonomyLevel.MANUAL]
    assert zero.default is AutonomyLevel.MANUAL

    cloud = compute_autonomy(Tier.CLOUD)
    assert cloud.default is AutonomyLevel.ASSIST
    assert AutonomyLevel.AUTO in cloud.available
    assert len(cloud.available) == 4


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
